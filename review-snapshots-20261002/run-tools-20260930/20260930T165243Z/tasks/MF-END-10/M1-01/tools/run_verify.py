"""M1-01 — chạy chuỗi verification cuối (§6 bước 3–8) và ghi log UTC.

Không dùng cho việc gì khác. Mọi lệnh in ra stdout thật; script KHÔNG tự kết
luận PASS/FAIL — nó chỉ ghi lại rc + thời lượng để reviewer đọc.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

W = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260930/M1-01")
FE = W / "frontend"
EV = Path(
    r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260930/20260930T165243Z/tasks/MF-END-10/M1-01"
)
RAW = EV / "raw"
RAW.mkdir(parents=True, exist_ok=True)
PY = sys.executable

CMD_LOG: list[dict] = []


def run(label: str, argv: list[str], cwd: Path, timeout: int = 1800) -> int:
    # `npx`/`npm` là script shell trên Windows: CreateProcess không spawn trực
    # tiếp được (WinError 2) → gọi qua shell.
    start = datetime.now(UTC)
    t0 = time.monotonic()
    proc = subprocess.run(
        argv, cwd=str(cwd), capture_output=True, text=True, timeout=timeout, shell=True
    )
    dur = time.monotonic() - t0
    (RAW / f"{label}.txt").write_text(
        f"$ {' '.join(argv)}\n\n--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}",
        encoding="utf-8",
    )
    CMD_LOG.append(
        {
            "label": label,
            "argv": argv,
            "cwd": str(cwd),
            "rc": proc.returncode,
            "started_at_utc": start.isoformat(),
            "ended_at_utc": datetime.now(UTC).isoformat(),
            "duration_seconds": round(dur, 2),
        }
    )
    tail = (proc.stdout.strip().splitlines() or [""])[-1]
    print(f"[{label}] rc={proc.returncode} {dur:.1f}s :: {tail[:90]}")
    return proc.returncode


# (0) dọn artifact test-results của chính lần chạy này (không thuộc allowlist)
tr = FE / "test-results"
removed = []
for child in sorted(tr.glob("mf-m1-character-create-*")):
    shutil.rmtree(child)
    removed.append(child.name)
print(f"[cleanup] removed {len(removed)} playwright artifact dirs")

env_prefix = {
    "M1_EVIDENCE_DIR": str(EV / "browser"),
}

# Playwright cần M1_EVIDENCE_DIR → truyền qua shell cho npx.
import os

os.environ["M1_EVIDENCE_DIR"] = str(EV / "browser")
Path(r"C:/Users/Admin/AppData/Local/Temp/mfm1-01-20260930/probe/env.json").write_text(
    json.dumps(
        {
            **env_prefix,
            "note": "env cho playwright; API 127.0.0.1:8071, UI 127.0.0.1:3071",
        },
        indent=1,
    ),
    encoding="utf-8",
)
run(
    "06_playwright_spec",
    ["npx", "playwright", "test", "e2e/mf-m1-character-create.spec.ts", "--reporter=list", "--workers=1"],
    FE,
)
run("05_pytest_mf_end_10", [PY, "-m", "pytest", "tests/product_delivery/test_mf_end_10.py", "-q", "--no-header"], W)
run("03eslint", ["npx", "eslint", "src/features/reference-library/CreateCharacterDialog.tsx", "src/app/(app)/characters/page.tsx", "src/features/reference-library/referenceLibraryApi.ts"], FE)
run("04tsc", ["npx", "tsc", "--noEmit"], FE)

# (7) build một lần trên frozen candidate
run("07_npm_build", ["npm", "run", "build"], FE)

(RAW / "commands_m1.jsonl").write_text(
    "\n".join(json.dumps(row, ensure_ascii=False) for row in CMD_LOG) + "\n", encoding="utf-8"
)
print("wrote", RAW / "commands_m1.jsonl", len(CMD_LOG), "rows")
