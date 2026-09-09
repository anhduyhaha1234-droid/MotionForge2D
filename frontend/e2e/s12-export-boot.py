"""S12-T05 boot wrapper — reset OWNED temp root -> alembic head -> seed ->
spawn uvicorn harness (wrapper keeps PID, Windows-safe, S07 pattern).

C25-part safe-QA-root contract (F10 fix):
- The temp root is deleted ONLY when it carries this file's ownership marker
  (``.s12t05-owner``) OR matches the exact per-run owned path pattern
  ``%TEMP%\\s12t05_root`` (task-claimed directory, never a parent/user path).
- Any other path (user home, repo, C:\\, a parent of the owned root, a path
  containing ``..`` that resolves outside, a junction/symlink/reparse point)
  is REJECTED: boot aborts before touching anything. No unchecked recursive
  deletion is ever performed.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

QA_ROOT = Path(os.environ["S12T05_QA_ROOT"])
BACKEND_ROOT = Path(os.environ["MF_BACKEND_ROOT"])
E2E_DIR = Path(__file__).resolve().parent

_OWNER_MARKER = ".s12t05-owner"
_OWNED_PATTERN = "s12t05_root"


def _is_owned_root(root: Path) -> tuple[bool, str]:
    """True only for a task-claimed temp root (marker OR exact name pattern)."""
    try:
        resolved = root.resolve()
    except OSError as err:
        return False, f"unresolvable root: {err}"
    tmp = Path(os.environ.get("TEMP", os.environ.get("TMP", "")))
    if tmp:
        try:
            tmp_res = Path(tmp).resolve()
            if not str(resolved).startswith(str(tmp_res)):
                return False, f"root {root} escapes TEMP {tmp_res}"
        except OSError as err:
            return False, f"unresolvable TEMP: {err}"
    marker = resolved / _OWNER_MARKER
    if marker.is_file():
        return True, f"ownership marker present: {marker}"
    if resolved.name == _OWNED_PATTERN and resolved.parent.name.lower().startswith("temp"):
        return True, f"owned-name pattern match: {resolved}"
    return False, (
        f"root {resolved} has no {_OWNER_MARKER} marker and is not the owned "
        f"temp pattern {_OWNED_PATTERN!r}; refusing to touch it"
    )


def _reject_reparse_points(root: Path) -> None:
    """Junction/symlink/reparse components are never followed for deletion."""
    import ctypes

    for part in [root, *root.parents]:
        if not part.exists():
            continue
        try:
            attrs = ctypes.windll.kernel32.GetFileAttributesW(str(part))
        except Exception:
            attrs = 0xFFFFFFFF
        if attrs != 0xFFFFFFFF and attrs & 0x400:  # FILE_ATTRIBUTE_REPARSE_POINT
            raise SystemExit(
                f"[boot] REFUSING reparse-point root component: {part} "
                f"(junction/symlink rejection, C25-part). Aborting before any deletion."
            )


def _reset_owned_root(root: Path) -> None:
    """Delete only an OWNED, non-reparse temp root; never anything else."""
    ok, reason = _is_owned_root(root)
    if not ok:
        raise SystemExit(
            f"[boot] REFUSING to delete {root}: {reason}. Aborting before any deletion."
        )
    _reject_reparse_points(root)
    marker = root.resolve() / _OWNER_MARKER
    try:
        marker.write_text("s12-t05 owned QA root (F10/C25 safe-reset contract)\n", encoding="utf-8")
    except OSError as err:
        raise SystemExit(f"[boot] cannot write ownership marker: {err}") from err
    print(f"[boot] resetting owned root {root.resolve()} (marker present)", flush=True)
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    (root / _OWNER_MARKER).write_text(
        "s12-t05 owned QA root (F10/C25 safe-reset contract)\n", encoding="utf-8"
    )


print(f"[boot] QA_ROOT={QA_ROOT}", flush=True)
_reset_owned_root(QA_ROOT)
(QA_ROOT / "data").mkdir(parents=True, exist_ok=True)
(QA_ROOT / "artifacts").mkdir(parents=True, exist_ok=True)

print("[boot] alembic head + seed via s12t05_seed_export.py ...", flush=True)
seed_env = os.environ.copy()
seed_env["MF_BACKEND_ROOT"] = str(BACKEND_ROOT)
seed_env["MF_DB_PATH"] = str(QA_ROOT / "data" / "motionforge.db")
seed_env["S12T05_QA_ROOT"] = str(QA_ROOT)
alembic_env = os.environ.copy()
alembic_env["MOTIONFORGE_ROOT"] = str(QA_ROOT)
alembic_env["MOTIONFORGE_DATABASE_URL"] = f"sqlite:///{(QA_ROOT / 'data' / 'motionforge.db').as_posix()}"
alembic = subprocess.run(
    [sys.executable, "-c",
     "from alembic.config import Config; from alembic import command; "
     "import os; c=Config('alembic.ini'); "
     "c.set_main_option('script_location','migrations'); "
     "c.set_main_option('sqlalchemy.url', os.environ['MOTIONFORGE_DATABASE_URL']); "
     "command.upgrade(c,'head')"],
    cwd=str(BACKEND_ROOT),
    env=alembic_env,
    capture_output=True,
    text=True,
    encoding="utf-8",
)
if alembic.returncode != 0:
    print("[boot] ALEMBIC FAILED", alembic.stdout[-4000:], alembic.stderr[-4000:], flush=True)
    sys.exit(alembic.returncode or 1)
proc = subprocess.run(
    [sys.executable, str(E2E_DIR / "s12-export-seed.py"), "export"],
    cwd=str(BACKEND_ROOT),
    env=seed_env,
    capture_output=True,
    text=True,
    encoding="utf-8",
)
if proc.returncode != 0:
    print("[boot] SEED FAILED", proc.stdout[-4000:], proc.stderr[-4000:], flush=True)
    sys.exit(proc.returncode or 1)
lines = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()]
seed = json.loads(lines[-1])
(QA_ROOT / "seed.json").write_text(json.dumps(seed, indent=2), encoding="utf-8")
print(f"[boot] seed.json written: {seed['project_id']}", flush=True)

print("[boot] spawn uvicorn harness (wrapper keeps PID)", flush=True)
server_env = os.environ.copy()
server_env["MOTIONFORGE_ROOT"] = str(QA_ROOT)
server_env["MOTIONFORGE_DATABASE_URL"] = f"sqlite:///{(QA_ROOT / 'data' / 'motionforge.db').as_posix()}"
server_env["MOTIONFORGE_CORS_ORIGINS"] = "http://localhost:3015,http://127.0.0.1:3015"
uvicorn = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "frontend.e2e.s12-export-harness:app",
     "--host", "127.0.0.1", "--port", "8415",
     "--log-level", "warning"],
    cwd=str(BACKEND_ROOT),
    env=server_env,
)


def _terminate_child(signum=None, frame=None):
    print(f"[boot] wrapper got signal {signum}, terminating uvicorn {uvicorn.pid}", flush=True)
    try:
        uvicorn.terminate()
    except Exception:
        pass
    try:
        uvicorn.wait(timeout=10)
    except Exception:
        try:
            uvicorn.kill()
        except Exception:
            pass
    sys.exit(0)


try:
    signal.signal(signal.SIGTERM, _terminate_child)
except Exception:
    pass
try:
    signal.signal(signal.SIGINT, _terminate_child)
except Exception:
    pass

try:
    exit_code = uvicorn.wait()
    print(f"[boot] uvicorn exited with {exit_code}", flush=True)
    sys.exit(exit_code)
except KeyboardInterrupt:
    _terminate_child()
finally:
    if uvicorn.poll() is None:
        try:
            uvicorn.terminate()
            uvicorn.wait(timeout=5)
        except Exception:
            try:
                uvicorn.kill()
            except Exception:
                pass
