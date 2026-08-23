"""Boot wrapper for the S07-T03 real-vertical backend webServer.

Playwright starts webServers BEFORE globalSetup, so the wipe+seed must
happen HERE (before uvicorn opens the SQLite file) — otherwise the
global-setup rmSync hits EPERM on Windows (uvicorn holds motionforge.db).

Sequence: wipe temp root (F-D: never trust residue) -> run the seed helper
-> write seed.json -> spawn uvicorn as child and keep wrapper PID for
Playwright teardown (Windows-safe, no os.execv orphan).

Fix F2: os.execv on Windows does NOT replace PID, it spawns a new python
process and exits wrapper -> Playwright kills wrapper PID, uvicorn stays
orphan holding 8004. This wrapper now spawns uvicorn via Popen, waits,
and forwards termination so the whole tree dies when Playwright kills the
wrapper.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ["MOTIONFORGE_ROOT"])
print(f"[boot] wiping temp root {ROOT}", flush=True)
shutil.rmtree(ROOT, ignore_errors=True)
(ROOT / "data").mkdir(parents=True, exist_ok=True)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
print("[boot] seeding via production repository...", flush=True)
proc = subprocess.run(
    [sys.executable, str(PROJECT_ROOT / "frontend/e2e/s07-t03-seed-helper.py")],
    cwd=str(PROJECT_ROOT),
    env=os.environ.copy(),
    capture_output=True,
    text=True,
    encoding="utf-8",
)
if proc.returncode != 0:
    print("[boot] SEED FAILED", proc.stdout[-4000:], proc.stderr[-4000:], flush=True)
    sys.exit(proc.returncode or 1)
lines = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()]
seed = json.loads(lines[-1])
(ROOT / "seed.json").write_text(json.dumps(seed, indent=2), encoding="utf-8")
print(f"[boot] seed.json written: {seed['projectId']}", flush=True)

print("[boot] spawn uvicorn (wrapper keeps PID)", flush=True)
# Windows-safe: keep wrapper alive, child is uvicorn. Playwright owns wrapper PID.
uvicorn = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "app.main:app",
     "--host", "127.0.0.1", "--port", "8004",
     "--log-level", "warning"],
    cwd=str(PROJECT_ROOT),
    env=os.environ.copy(),
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

# Forward SIGTERM/SIGINT to child so Playwright's teardown kills the tree
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
    # Ensure child is gone if wrapper exits for any other reason
    if uvicorn.poll() is None:
        try:
            uvicorn.terminate()
            uvicorn.wait(timeout=5)
        except Exception:
            try:
                uvicorn.kill()
            except Exception:
                pass
