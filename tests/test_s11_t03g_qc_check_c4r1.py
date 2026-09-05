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


_PAYLOAD_R2_IMPORT_FAIL = """\
import json, sys
from pathlib import Path
ROOT = Path(%(root)r)
sys.path.insert(0, str(ROOT))
from app.services.qc_checks.registry import registry
from app.workflow import qc_checks_handler as handler
from app.workflow.qc_checks_handler import (
    SCOPE_FULL, ensure_full_band_registered, scope_detectors,
)


def snap4():
    return [
        (n, registry.get(n).entry_point, registry.get(n).version,
         registry.get(n).description)
        for n in registry.names()
    ]


band = scope_detectors(SCOPE_FULL)
# Seed a foreign entry so the pre-call snapshot is non-trivial.
registry.register(
    "r2_probe_foreign",
    "app.services.qc_checks.audio_missing:detect",
    version="7.7.7",
    description="r2-import-fail-probe",
)
pre = snap4()
# Poison the NEXT import: trajectory_drift self-registers at module level,
# so a RuntimeError side effect there must still restore the full snapshot.
real_register = registry.register
calls = {"n": 0, "fired": False}

def poisoned(name, entry_point, **kwargs):
    calls["n"] += 1
    if name == "trajectory_drift" and not calls["fired"]:
        calls["fired"] = True
        spec = real_register(name, entry_point, **kwargs)
        raise RuntimeError("r2-import-side-effect-boom")
    return real_register(name, entry_point, **kwargs)

registry.register = poisoned
report = {}
try:
    ensure_full_band_registered()
    report["outcome"] = "UNEXPECTED_SUCCESS"
except Exception as exc:
    report["outcome"] = type(exc).__name__
    report["code"] = getattr(exc, "code", None)
    cause = exc.__cause__
    report["cause"] = type(cause).__name__ if cause is not None else None
    report["cause_msg"] = str(cause) if cause is not None else None
finally:
    registry.register = real_register
report["restored"] = snap4() == pre
report["pre_len"] = len(pre)
for n in list(registry.names()):
    registry.unregister(n)
# Clean bootstrap afterwards must still reach the exact ten-band.
revs = ensure_full_band_registered()
report["clean_names_eq_band"] = list(registry.names()) == band
report["clean_count"] = len(registry.names())
report["revs_ok"] = all(isinstance(v, str) and v for v in revs.values())
print("C4R1-JSON:" + json.dumps(report))
"""

_PAYLOAD_R2_EXPLICIT_FAIL = """\
import json, sys
from pathlib import Path
ROOT = Path(%(root)r)
sys.path.insert(0, str(ROOT))
from app.services.qc_checks.registry import registry
from app.workflow import qc_checks_handler as handler
from app.workflow.qc_checks_handler import (
    SCOPE_FULL, ensure_full_band_registered, scope_detectors,
)


def snap4():
    return [
        (n, registry.get(n).entry_point, registry.get(n).version,
         registry.get(n).description)
        for n in registry.names()
    ]


band = scope_detectors(SCOPE_FULL)
ensure_full_band_registered()
# Pre-call snapshot is the exact ten-band (no foreign entry: the foreign
# leg is already covered by the R1 matrix; here the failure must come
# from the explicit-registration leg itself).
pre = snap4()
# Poison the explicit-registration leg: contact_break.register() runs inside
# the bootstrap AFTER imports, so its side effect + RuntimeError must roll
# back to the exact pre-call snapshot.
import app.services.qc_checks.contact_break as contact_break_mod
real_cb_register = contact_break_mod.register

def poisoned_cb(**kwargs):
    spec = real_cb_register(**kwargs)
    raise RuntimeError("r2-explicit-side-effect-boom")

contact_break_mod.register = poisoned_cb
report = {}
try:
    ensure_full_band_registered()
    report["outcome"] = "UNEXPECTED_SUCCESS"
except Exception as exc:
    report["outcome"] = type(exc).__name__
    report["code"] = getattr(exc, "code", None)
    cause = exc.__cause__
    report["cause"] = type(cause).__name__ if cause is not None else None
    report["cause_msg"] = str(cause) if cause is not None else None
finally:
    contact_break_mod.register = real_cb_register
report["restored"] = snap4() == pre
report["pre_len"] = len(pre)
for n in list(registry.names()):
    registry.unregister(n)
revs = ensure_full_band_registered()
report["clean_names_eq_band"] = list(registry.names()) == band
report["clean_count"] = len(registry.names())
report["revs_ok"] = all(isinstance(v, str) and v for v in revs.values())
print("C4R1-JSON:" + json.dumps(report))
"""

_PAYLOAD_R2_TWO_THREAD = """\
import json, sys, threading
from pathlib import Path
ROOT = Path(%(root)r)
sys.path.insert(0, str(ROOT))
from app.services.qc_checks.registry import registry
from app.workflow import qc_checks_handler as handler
from app.workflow.qc_checks_handler import (
    SCOPE_FULL, ensure_full_band_registered, scope_detectors,
)


def snap4():
    return [
        (n, registry.get(n).entry_point, registry.get(n).version,
         registry.get(n).description)
        for n in registry.names()
    ]


band = scope_detectors(SCOPE_FULL)
for n in list(registry.names()):
    registry.unregister(n)
# Contested bootstrap: the main thread seeds a foreign ghost, then two live
# threads race at the barrier.  The failer must lose with a stable
# BOOTSTRAP_CONFLICT (its stale rollback restores ONLY its pre-call
# snapshot); the succeeder waits for the failure event, removes the ghost,
# and converges to the exact ordered ten-band.  Joins are bounded and raw
# outcomes are captured.
registry.register(
    "r2_ghost",
    "app.services.qc_checks.audio_missing:detect",
    version="9.9.9",
    description="r2-race-ghost",
)
report = {}
barrier = threading.Barrier(2)
f_failed = threading.Event()
outcomes = {}

def failer():
    barrier.wait(timeout=10)
    try:
        ensure_full_band_registered()
        outcomes["failer"] = {"ok": True}
    except Exception as exc:
        outcomes["failer"] = {"ok": False, "type": type(exc).__name__,
                              "code": getattr(exc, "code", None),
                              "restored_ghost": (
                                  list(registry.names()) == ["r2_ghost"])}

def succeeder():
    barrier.wait(timeout=10)
    f_failed.wait(timeout=30)
    registry.unregister("r2_ghost")
    try:
        revs = ensure_full_band_registered()
        outcomes["succeeder"] = {"ok": True, "revs": len(revs)}
    except Exception as exc:
        outcomes["succeeder"] = {"ok": False, "type": type(exc).__name__,
                                 "code": getattr(exc, "code", None)}

def failer_wrapped():
    try:
        failer()
    finally:
        f_failed.set()

ta = threading.Thread(target=failer_wrapped)
tb = threading.Thread(target=succeeder)
ta.start()
tb.start()
ta.join(timeout=60)
tb.join(timeout=60)
report["a_alive"] = ta.is_alive()
report["b_alive"] = tb.is_alive()
report["outcomes"] = outcomes
# One succeeder path: a clean retry converges to the exact ordered ten-band.
revs = ensure_full_band_registered()
report["final_names_eq_band"] = list(registry.names()) == band
report["final_count"] = len(registry.names())
report["revs_ok"] = all(isinstance(v, str) and v for v in revs.values())
print("C4R1-JSON:" + json.dumps(report))
"""


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
    """Ghost plus the two conflicting-identity rows restore pre-call state."""
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


def test_c4r2_import_side_effect_rolls_back_full_snapshot() -> None:
    """Import-leg RuntimeError restores the exact FULL snapshot (§4 row 5)."""
    report = _run_payload(_PAYLOAD_R2_IMPORT_FAIL)
    assert report["outcome"] == "RunQcChecksError", report
    assert report["code"] == "QC_RUN_BOOTSTRAP_CONFLICT", report
    assert report["cause"] == "RuntimeError", report
    assert "r2-import-side-effect-boom" in (report["cause_msg"] or ""), report
    assert report["restored"] is True, report
    assert report["pre_len"] == 1, report
    assert report["clean_names_eq_band"] is True, report
    assert report["clean_count"] == 10, report
    assert report["revs_ok"] is True, report


def test_c4r2_explicit_registration_side_effect_rolls_back() -> None:
    """Explicit-registration RuntimeError restores the FULL snapshot (row 6)."""
    report = _run_payload(_PAYLOAD_R2_EXPLICIT_FAIL)
    assert report["outcome"] == "RunQcChecksError", report
    assert report["code"] == "QC_RUN_BOOTSTRAP_CONFLICT", report
    assert report["cause"] == "RuntimeError", report
    assert "r2-explicit-side-effect-boom" in (report["cause_msg"] or ""), report
    assert report["restored"] is True, report
    assert report["pre_len"] == 10, report
    assert report["clean_names_eq_band"] is True, report
    assert report["clean_count"] == 10, report
    assert report["revs_ok"] is True, report


def test_c4r2_two_live_threads_contested_bootstrap_converges() -> None:
    """Two live threads at contested bootstrap converge to ten-band (row 7)."""
    report = _run_payload(_PAYLOAD_R2_TWO_THREAD)
    assert report["a_alive"] is False, report
    assert report["b_alive"] is False, report
    assert set(report["outcomes"]) == {"failer", "succeeder"}, report
    failer = report["outcomes"]["failer"]
    succeeder = report["outcomes"]["succeeder"]
    assert failer["ok"] is False, report
    assert failer["type"] == "RunQcChecksError", report
    assert failer["code"] == "QC_RUN_BOOTSTRAP_CONFLICT", report
    assert succeeder["ok"] is True, report
    assert succeeder["revs"] == 10, report
    assert report["final_names_eq_band"] is True, report
    assert report["final_count"] == 10, report
    assert report["revs_ok"] is True, report
