"""S12-T05 boot wrapper — wipe temp root -> alembic head -> seed ->
spawn uvicorn harness (wrapper keeps PID, Windows-safe, S07 pattern).
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

print(f"[boot] wiping temp root {QA_ROOT}", flush=True)
shutil.rmtree(QA_ROOT, ignore_errors=True)
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
