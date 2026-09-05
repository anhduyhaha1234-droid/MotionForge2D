"""S11-C4-R1 durable clean-process bootstrap proof (narrow subprocess test).

Spawns a FRESH interpreter that starts with an EMPTY detector registry,
imports ONLY ordinary app code (never detector modules, never test
fixtures), constructs the real production ``JobService`` over a fresh
Alembic-head DB, and asserts the hook deterministically registered the
binding FULL band (exact set, exact order, exact revisions).  Fails if the
``JobService.__init__`` hook is removed: without it the registry stays
empty.  Also asserts full snapshot/rollback: ghost entries are rejected
and every conflict failure restores the exact pre-call registry.
"""

import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_PAYLOAD_CLEAN_BOOTSTRAP = """\
import json, sys, tempfile
from pathlib import Path
ROOT = Path(%(root)r)
sys.path.insert(0, str(ROOT))
from app.services.qc_checks.registry import registry
pre = list(registry.names())
from app.persistence import create_engine_for_path, create_session_factory
from alembic import command as alembic_command
from alembic.config import Config
tmp = Path(tempfile.mkdtemp(prefix="s11c4r1_clean_"))
db = tmp / "t03g.db"
managed = tmp / "managed"
managed.mkdir(exist_ok=True)
eng = create_engine_for_path(db)
cfg = Config(str(ROOT / "alembic.ini"))
cfg.set_main_option("script_location", str(ROOT / "migrations"))
cfg.set_main_option("sqlalchemy.url", "sqlite:///" + db.as_posix())
alembic_command.upgrade(cfg, "head")
from app.workflow.job_service import JobService
svc = JobService(create_session_factory(eng), managed_root=managed)
assert svc.worker is not None
from app.workflow.qc_checks_handler import (
    SCOPE_FULL, detector_revisions, scope_detectors,
)
band = scope_detectors(SCOPE_FULL)
post = list(registry.names())
revs = detector_revisions(band)
print("C4R1-JSON:" + json.dumps({
    "pre": pre, "post": post, "band": band, "revisions": revs,
}))
"""

_PAYLOAD_ROLLBACK = """\
import json, sys
from pathlib import Path
ROOT = Path(%(root)r)
sys.path.insert(0, str(ROOT))
from app.services.qc_checks.registry import registry
from app.workflow.qc_checks_handler import (
    SCOPE_FULL, ensure_full_band_registered, scope_detectors,
)


def snap():
    return [
        (n, registry.get(n).entry_point, registry.get(n).version)
        for n in registry.names()
    ]


band = scope_detectors(SCOPE_FULL)
report = {}

# Case 1: ghost entry -> reject + exact restore.
registry.register(
    "ghost_detector",
    "app.services.qc_checks.audio_missing:detect",
    version="1.0.0",
)
pre = snap()
try:
    ensure_full_band_registered()
    report["ghost"] = "UNEXPECTED_SUCCESS"
except Exception as exc:
    report["ghost"] = type(exc).__name__
report["ghost_restored"] = snap() == pre
registry.unregister("ghost_detector")

# Case 2: same-name different-entry conflict -> raise + exact restore.
registry.register(
    "trajectory_drift",
    "app.services.qc_checks.cut_drift:detect",
    version="9.9.9",
)
pre = snap()
try:
    ensure_full_band_registered()
    report["entry_conflict"] = "UNEXPECTED_SUCCESS"
except Exception as exc:
    report["entry_conflict"] = type(exc).__name__
report["entry_restored"] = snap() == pre
registry.unregister("trajectory_drift")

# Case 3: same-name/entry different-version -> raise + exact restore.
# (Registry launders versions on import, so seed the conflicting version
# AFTER the band is registered once.)
ensure_full_band_registered()
spec = registry.get("audio_missing")
registry.unregister("audio_missing")
registry.register(
    "audio_missing", spec.entry_point, version="0.0.0-conflict"
)
pre = snap()
try:
    ensure_full_band_registered()
    report["version_conflict"] = "UNEXPECTED_SUCCESS"
except Exception as exc:
    report["version_conflict"] = type(exc).__name__
report["version_restored"] = snap() == pre
for n in list(registry.names()):
    registry.unregister(n)

# Case 4: clean success is exact (set/order/revisions) + idempotent.
revs1 = ensure_full_band_registered()
revs2 = ensure_full_band_registered()
report["clean_names_eq_band"] = list(registry.names()) == band
report["clean_count"] = len(registry.names())
report["idempotent"] = revs1 == revs2
print("C4R1-JSON:" + json.dumps(report))
"""


def _run_payload(payload: str) -> dict:
    proc = subprocess.run(
        [sys.executable, "-c", payload % {"root": str(PROJECT_ROOT)}],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, (
        f"clean subprocess failed rc={proc.returncode}\n"
        f"STDOUT:\n{proc.stdout[-2000:]}\nSTDERR:\n{proc.stderr[-2000:]}"
    )
    for line in proc.stdout.splitlines():
        if line.startswith("C4R1-JSON:"):
            return json.loads(line[len("C4R1-JSON:"):])
    raise AssertionError(f"no C4R1-JSON in subprocess stdout:\n{proc.stdout[-2000:]}")


def test_c4r1_clean_process_jobservice_registers_full_band() -> None:
    """Durable regression: real JobService registers the FULL band."""
    report = _run_payload(_PAYLOAD_CLEAN_BOOTSTRAP)
    assert report["pre"] == [], report
    assert report["post"] == report["band"], report
    assert len(report["post"]) == 10, report
    assert all(
        isinstance(value, str) and value for value in report["revisions"].values()
    ), report


def test_c4r1_bootstrap_rejects_ghost_and_restores_snapshot() -> None:
    """Ghost rejected; every conflict restores the exact pre-call state."""
    report = _run_payload(_PAYLOAD_ROLLBACK)
    assert report["ghost"] == "RunQcChecksError", report
    assert report["ghost_restored"] is True, report
    assert report["entry_conflict"] == "RunQcChecksError", report
    assert report["entry_restored"] is True, report
    assert report["version_conflict"] == "RunQcChecksError", report
    assert report["version_restored"] is True, report
    assert report["clean_names_eq_band"] is True, report
    assert report["clean_count"] == 10, report
    assert report["idempotent"] is True, report
