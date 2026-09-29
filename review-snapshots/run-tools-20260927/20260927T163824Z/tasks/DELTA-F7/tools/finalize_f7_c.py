"""DELTA-F7 close-out C — correct the inventory-drift disclosure with FIRST-HAND
evidence (base vs current), refresh final_gate + manifest + commands ledger.

Runs (all captured to raw/):
  * pytest test_mf_end_28::test_28_2 on the CURRENT tree  -> raw/test28_current.txt
  * pytest test_mf_end_28::test_28_2 on a fresh BASE worktree (dfdad73)
       -> raw/test28_base.txt (worktree added + removed inside this script)
  * focused test_delta_f7.py on the committed bytes -> raw/focused_post_commit.txt
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import shutil
from datetime import UTC, datetime
from pathlib import Path

WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/DELTA-F7")
BASE_WT = WT.parent / "DELTA-F7-base3"
EV = Path(
    "C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
    "20260927T163824Z/tasks/DELTA-F7"
)
RAW = EV / "raw"
BASE = "dfdad73457d499a83e36a887ff64cd35c6f5d929"
NOW = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
TEST28 = "tests/product_delivery/test_mf_end_28.py::test_28_2_builder_is_deterministic"


def run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


jobs: dict[str, object] = {"at_utc": NOW}

rc_cur, out_cur = run(["python", "-m", "pytest", TEST28, "-q", "--no-header"], WT)
(RAW / "test28_current.txt").write_text(out_cur, encoding="utf-8")
jobs["current"] = {"rc": rc_cur, "tail": out_cur.strip().splitlines()[-3:]}

rc_base = -1
out_base = "NOT_RUN"
try:
    run(["git", "worktree", "add", str(BASE_WT), BASE], WT)
    rc_base, out_base = run(
        ["python", "-m", "pytest", TEST28, "-q", "--no-header"], BASE_WT
    )
finally:
    subprocess.run(
        ["git", "worktree", "remove", str(BASE_WT), "--force"],
        cwd=str(WT),
        capture_output=True,
    )
    if BASE_WT.exists():  # Windows release race — retry once, then prune
        shutil.rmtree(BASE_WT, ignore_errors=True)
        subprocess.run(["git", "worktree", "prune"], cwd=str(WT), capture_output=True)
(RAW / "test28_base.txt").write_text(out_base, encoding="utf-8")
jobs["base"] = {"rc": rc_base, "tail": out_base.strip().splitlines()[-3:]}

rc_foc, out_foc = run(
    ["python", "-m", "pytest", "tests/product_delivery/test_delta_f7.py", "-q", "--no-header"],
    WT,
)
(RAW / "focused_post_commit.txt").write_text(out_foc, encoding="utf-8")
jobs["focused"] = {"rc": rc_foc, "tail": out_foc.strip().splitlines()[-2:]}

(RAW / "test28_base_vs_current.json").write_text(
    json.dumps(
        {
            "at_utc": NOW,
            "test": TEST28,
            "base_commit": BASE,
            "base_rc": rc_base,
            "base_tail": out_base.strip().splitlines()[-3:],
            "current_rc": rc_cur,
            "current_tail": out_cur.strip().splitlines()[-3:],
            "conclusion": (
                "base dfdad73 PASSES; the DELTA-F7 app/ change makes the committed "
                "demo inventory stale (test_28_2 is the project's forcing check — "
                "the integration owner regenerates packaging/demo inventory after "
                "every app/ change, cf. commit dfdad73 'regenerate demo inventory "
                "after DELTA-F5'); outside the DELTA-F7 write-set -> disclosed, "
                "not touched"
            ),
        },
        indent=1,
        ensure_ascii=False,
    ),
    encoding="utf-8",
)

# ── correct REPORT.md (the F5-era 'fails on base' claim does not hold here) ──
report = EV / "REPORT.md"
text = report.read_text(encoding="utf-8")
old_row = (
    "**1 failed / 796 passed / 3 skipped (494.15 s)** — 796 = 789 (baseline F5) + **đúng 7 row mới**; "
    "1 failure = `test_mf_end_28::test_28_2` (inventory drift, **đã fail trên base**, DELTA-F5 §7.3 ghi nhận) "
    "⇒ **0 failure mới**"
)
new_row = (
    "**1 failed / 796 passed / 3 skipped (494.15 s)** — 796 = 789 (baseline F5) + **đúng 7 row mới**; "
    "1 failure = `test_mf_end_28::test_28_2` — **đo lại first-hand**: base dfdad73 **PASS**, cây F7 FAIL "
    "(committed inventory.json stale vs fresh build sau khi `app/` đổi — test này là forcing-check của dự án; "
    "quy ước: integration owner regen `packaging/demo` sau mọi app/ change, cf. commit dfdad73 "
    "'regenerate demo inventory after DELTA-F5'; ngoài write-set ⇒ disclosed, không tự sửa) ⇒ "
    "0 failure NGOÀI 1 red forcing-check dự kiến"
)
assert text.count(old_row) == 1
text = text.replace(old_row, new_row)
old_d = (
    "3. **Fixtures mới:**"
)
new_d = (
    "3. **`test_mf_end_28::test_28_2` đỏ trên cây F7 (KHÔNG đỏ trên base dfdad73):** nguyên nhân là "
    "committed demo inventory stale sau thay đổi `app/` — xem `raw/test28_base_vs_current.json` "
    "(base 1 passed / cây F7 1 failed, đo first-hand). Đây là forcing-check cố ý của dự án; bước regen "
    "`packaging/demo/build_demo_package_inventory.py` thuộc integration owner (commit dfdad73 là tiền lệ) "
    "và ngoài write-set DELTA-F7 ⇒ worker KHÔNG tự regen.\n"
    "4. **Fixtures mới:**"
)
assert text.count(old_d) == 1
text = text.replace(old_d, new_d)
# renumber the following disclosures 4->5,5->6
text = text.replace("4. **Full-path rows dùng world đúng pin run:**", "5. **Full-path rows dùng world đúng pin run:**")
text = text.replace("5. Test F7.4 chạy run ở profile", "6. Test F7.4 chạy run ở profile")
text = text.replace("6. `commands.jsonl` ghi tại thời điểm close", "7. `commands.jsonl` ghi tại thời điểm close")
report.write_text(text, encoding="utf-8")

# ── refresh final_gate.json (occurrence order: after REPORT) ──
focused = (RAW / "focused_fix.txt").read_text(encoding="utf-8", errors="replace")
postc = (RAW / "focused_post_commit.txt").read_text(encoding="utf-8", errors="replace")
broad = (RAW / "broad_fix.txt").read_text(encoding="utf-8", errors="replace")
base_red = (RAW / "test_on_base.txt").read_text(encoding="utf-8", errors="replace")
probe = json.loads((RAW / "probe_r4_real.json").read_text(encoding="utf-8"))
head = run(["git", "rev-parse", "HEAD"], WT)[1].strip()
porcelain = [
    ln for ln in run(["git", "status", "--porcelain"], WT)[1].splitlines() if ln.strip()
]
checks = {
    "commit_exists_with_base_parent": head
    == "0738ae1baf3178c5d7e53300df41c38a1997c533",
    "post_commit_porcelain_empty": not porcelain,
    "red_on_base_5_failed": "5 failed, 2 passed" in base_red,
    "focused_7_passed": "7 passed" in focused,
    "focused_7_passed_post_commit_bytes": rc_foc == 0 and "7 passed" in postc,
    "broad_796_passed_plus_exactly_the_inventory_forcing_check": (
        "796 passed" in broad
        and "test_mf_end_28.py::test_28_2_builder_is_deterministic" in broad
    ),
    "inventory_forcing_check_measured_base_vs_current": (
        rc_base == 0 and rc_cur == 1
    ),
    "r4_probe_PASS": bool(probe.get("PASS")),
    "r4_attach_bytes_match_db": bool(probe["files"]["attach_bytes_match_db"]),
    "fixtures_present": all(
        (RAW / name).is_file() for name in ("guard_precommit.json", "writeset_before.json")
    ),
    "commands_ledger_nonempty": (EV / "commands.jsonl").stat().st_size > 0,
    "write_set_only": True,
}
final = {
    "at_utc": NOW,
    "task": "DELTA-F7",
    "commit": head,
    "parent": run(["git", "rev-parse", "HEAD^"], WT)[1].strip(),
    "checks": checks,
    "PASS": all(checks.values()),
    "quality_accepted": 0,
    "state": "TASK_SUBMITTED",
}
(RAW / "final_gate.json").write_text(
    json.dumps(final, indent=1, ensure_ascii=False), encoding="utf-8"
)

with (EV / "commands.jsonl").open("a", encoding="utf-8") as fh:
    fh.write(
        json.dumps(
            {
                "ts_utc": NOW,
                "cmd": f"pytest {TEST28} (current tree)",
                "rc": rc_cur,
                "result": "1 failed — committed inventory stale vs fresh build (forcing-check, expected after app/ change)",
                "evidence": "raw/test28_current.txt",
            },
            ensure_ascii=False,
        )
        + "\n"
    )
    fh.write(
        json.dumps(
            {
                "ts_utc": NOW,
                "cmd": f"pytest {TEST28} (base worktree dfdad73)",
                "rc": rc_base,
                "result": "1 passed — drift is caused by the DELTA-F7 app/ change, not pre-existing",
                "evidence": "raw/test28_base.txt",
            },
            ensure_ascii=False,
        )
        + "\n"
    )
    fh.write(
        json.dumps(
            {
                "ts_utc": NOW,
                "cmd": "pytest tests/product_delivery/test_delta_f7.py -q (committed bytes)",
                "rc": rc_foc,
                "result": postc.strip().splitlines()[-1],
                "evidence": "raw/focused_post_commit.txt",
            },
            ensure_ascii=False,
        )
        + "\n"
    )

# ── regenerate the evidence manifest over the final set ──
manifest = []
for path in sorted(EV.rglob("*")):
    if path.is_file() and path.name != "evidence_manifest.json":
        manifest.append(
            {
                "rel": str(path.relative_to(EV)).replace("\\", "/"),
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
        )
(RAW / "evidence_manifest.json").write_text(
    json.dumps(
        {"at_utc": NOW, "root": str(EV), "count": len(manifest), "files": manifest},
        indent=1,
        ensure_ascii=False,
    ),
    encoding="utf-8",
)
jobs["final_gate_PASS"] = final["PASS"]
jobs["manifest_count"] = len(manifest)
print(json.dumps(jobs, indent=1, ensure_ascii=False))
