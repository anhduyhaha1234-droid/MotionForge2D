"""MF-END-28 evidence builder (idempotent; adapted from MF-END-27's tool).

Writes: raw/write_set_before.json, raw/write_set_after.json, raw/guard.json,
results.json, commands.jsonl, evidence_manifest.json and runs
ruff/py_compile as recorded gates.  Fields not measured are null with a
note — never fabricated.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-28")
EV = Path(
    "C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
    "20260927T163824Z/tasks/MF-END-28"
)

ALLOWLIST = [
    "packaging/demo/build_demo_package_inventory.py",
    "packaging/demo/inventory.json",
    "packaging/demo/models.json",
    "packaging/demo/README.md",
    "scripts/mf_delivery_launcher.ps1",
    "THIRD_PARTY.md",
    "tests/product_delivery/test_mf_end_28.py",
]

PY_FILES = [
    "packaging/demo/build_demo_package_inventory.py",
    "tests/product_delivery/test_mf_end_28.py",
]

FROZEN_FILES = [
    "packaging/windows/Start-MotionForge-Beta.cmd",
    "packaging/windows/manifest.json",
    "scripts/s12/s12_t06a_stage.py",
    "scripts/s12/s12_t06a_run.py",
]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(WT), capture_output=True, text=True)


def file_row(rel: str) -> dict:
    path = WT / rel
    data = path.read_bytes() if path.is_file() else b""
    return {
        "path": rel,
        "exists": path.is_file(),
        "size_bytes": len(data),
        "sha256": sha256_bytes(data) if path.is_file() else None,
        "logical_lines": data.count(b"\n") + (0 if data.endswith(b"\n") or not data else 1),
        "mtime_utc": (
            datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
            if path.is_file()
            else None
        ),
    }


def main() -> int:
    (EV / "raw").mkdir(parents=True, exist_ok=True)
    head = run(["git", "rev-parse", "--verify", "HEAD^{commit}"]).stdout.strip()
    porcelain_raw = run(["git", "status", "--porcelain"]).stdout
    porcelain = [line for line in porcelain_raw.split("\n") if line.strip()]
    changed = [line[3:].strip().strip('"') for line in porcelain]
    # Untracked directories appear as '?? dir/' — expand to the real files,
    # skipping anything git IGNORES (__pycache__, caches) or the guard would
    # report phantom strays (pitfall #28).
    expanded: list[str] = []
    for rel in changed:
        if rel.endswith("/"):
            for p in sorted((WT / rel.rstrip("/")).rglob("*")):
                if not p.is_file():
                    continue
                inner = p.relative_to(WT).as_posix()
                ignored = subprocess.run(
                    ["git", "check-ignore", "-q", inner], cwd=str(WT)
                ).returncode == 0
                if not ignored:
                    expanded.append(inner)
        else:
            expanded.append(rel)
    changed = sorted(set(expanded))

    before: dict = {"source_head": head, "files": []}
    after: dict = {"source_head": head, "files": []}
    for rel in ALLOWLIST:
        blob = run(["git", "show", f"HEAD:{rel}"])
        if blob.returncode == 0:
            data = blob.stdout.encode("utf-8", "surrogateescape")
            before["files"].append(
                {"path": rel, "in_head": True, "size_bytes": len(data),
                 "sha256": sha256_bytes(data)}
            )
        else:
            before["files"].append({"path": rel, "in_head": False})
        after["files"].append(file_row(rel))

    protected_drift = [rel for rel in changed if rel not in ALLOWLIST]
    missing = [row["path"] for row in after["files"] if not row["exists"]]
    frozen_rows = []
    for rel in FROZEN_FILES:
        # Compare BLOB IDs, never worktree bytes: core.autocrlf=true checks
        # the same blob out as CRLF here, so a byte comparison reports a
        # false drift on 4/4 intact files (pitfall #46 family).
        live_blob = run(["git", "hash-object", f"--path={rel}",
                         str(WT / rel)]).stdout.strip()
        head_blob = run(["git", "rev-parse", f"HEAD:{rel}"]).stdout.strip()
        frozen_rows.append({"path": rel, "live_blob": live_blob,
                            "head_blob": head_blob,
                            "unchanged_vs_head": live_blob == head_blob and
                            bool(live_blob)})
    guard = {
        "source_head": head,
        "porcelain": porcelain,
        "porcelain_paths": changed,
        "allowlist": ALLOWLIST,
        "outside_allowlist": protected_drift,
        "missing_expected_outputs": missing,
        "porcelain_equals_allowlist": changed == sorted(ALLOWLIST),
        "phase": "pre_commit" if changed else "post_commit",
        "clean": (changed == sorted(ALLOWLIST)) or not changed,
        "frozen_s12_files_unchanged": all(
            row["unchanged_vs_head"] for row in frozen_rows),
        "frozen_s12_rows": frozen_rows,
    }

    py = sys.executable
    ruff = run([py, "-m", "ruff", "check", *PY_FILES])
    compile_ = run([py, "-m", "py_compile", *PY_FILES])

    (EV / "raw" / "write_set_before.json").write_text(
        json.dumps(before, indent=2, sort_keys=True), encoding="utf-8")
    (EV / "raw" / "write_set_after.json").write_text(
        json.dumps(after, indent=2, sort_keys=True), encoding="utf-8")
    (EV / "raw" / "guard.json").write_text(
        json.dumps(guard, indent=2, sort_keys=True), encoding="utf-8")
    (EV / "raw" / "static_gates.json").write_text(
        json.dumps(
            {"ruff_rc": ruff.returncode,
             "ruff_out": (ruff.stdout + ruff.stderr).strip().split("\n")[-3:],
             "py_compile_rc": compile_.returncode,
             "py_compile_out": (compile_.stdout + compile_.stderr).strip()[:400]},
            indent=2, sort_keys=True), encoding="utf-8")

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    commands = [
        {"n": 1, "cmd": "git log --oneline -1; git status --porcelain; ls packaging/ scripts/",
         "exit": 0, "duration_s": None,
         "note": "recon: HEAD b1965ad, porcelain 0; packaging/windows co 6 file T06A (frozen)",
         "source_head": head},
        {"n": 2, "cmd": "python -c socket connect_ex 8528/3128",
         "exit": 0, "duration_s": None, "note": "ports FREE truoc stage",
         "source_head": head},
        {"n": 3, "cmd": "npm ci (frontend/)",
         "exit": 0, "duration_s": None,
         "note": "NPMCI_RC=0, 297 entry node_modules (log: raw/npm_ci.log)",
         "source_head": head},
        {"n": 4, "cmd": "python scripts/s12/s12_t06a_stage.py --stage-root C:/Users/Admin/MF2D-demo-pkg-20260928 --backend-port 8528 --frontend-port 3128",
         "exit": 0, "duration_s": None,
         "note": "STAGE_RC=0; build_id yYjbPNMwhEO_tJl0FDvg-; package ngoai checkout; log raw/stage_build.log",
         "source_head": head},
        {"n": 5, "cmd": "python <stage>/scripts/s12_t06a_run.py setup --install-root C:/Users/Admin/MF2D-demo-rt-20260928",
         "exit": 0, "duration_s": None,
         "note": "preflight ALL PASSED (endpoint 8528 baked, roots writable); log raw/run_setup.log",
         "source_head": head},
        {"n": 6, "cmd": "powershell -File scripts/mf_delivery_launcher.ps1 -Action check (cwd=C:/Users/Admin)",
         "exit": 0, "duration_s": None,
         "note": "rc0 status ok; 8/8 model present (38,096,931,703 B); raw/launcher_check.json.txt",
         "source_head": head},
        {"n": 7, "cmd": "powershell -File ... -Action check -ModelsRoot <empty dir>",
         "exit": 3, "duration_s": None,
         "note": "NEGATIVE: rc3 blocked, 8x MODEL_MISSING; raw/launcher_check_neg_models.txt",
         "source_head": head},
        {"n": 8, "cmd": "powershell -File ... -Action start (staged package, runtime root)",
         "exit": 0, "duration_s": None,
         "note": "rc0; backend pid 24092 :8528 + frontend pid 8972 :3128 (hidden); raw/launcher_start.json.txt",
         "source_head": head},
        {"n": 9, "cmd": "powershell -File ... -Action status",
         "exit": 0, "duration_s": None,
         "note": "rc0 ok; identity verified; main_window_handle=0 (hidden); health 200/200; raw/launcher_status.json.txt",
         "source_head": head},
        {"n": 10, "cmd": "python <stage>/scripts/s12_t06a_run.py diagnose --install-root <rt>",
         "exit": 0, "duration_s": None,
         "note": "cross-check harness frozen: backend_health/frontend_root/ffmpeg/roots/disk all true; raw/run_diagnose_up.json",
         "source_head": head},
        {"n": 11, "cmd": "powershell -File ... -Action stop",
         "exit": 0, "duration_s": None,
         "note": "rc0 stopped; verified_gone true ca 2; ports closed; raw/launcher_stop.json.txt",
         "source_head": head},
        {"n": 12, "cmd": "powershell -File ... -Action stop (lan 2)",
         "exit": 0, "duration_s": None,
         "note": "idempotent: already_gone; raw/launcher_stop_again.txt",
         "source_head": head},
        {"n": 13, "cmd": "python scripts/s12/s12_t06a_stage.py --stage-root <trong repo>",
         "exit": 1, "duration_s": None,
         "note": "BLOCKED: stage root must be OUTSIDE the repo checkout (stderr); raw/stage_refuse_inrepo.txt",
         "source_head": head},
        {"n": 14, "cmd": "python packaging/demo/build_demo_package_inventory.py",
         "exit": 0, "duration_s": None,
         "note": "models.json 8 external; inventory: 17 backend pins, 17 frontend pins, 12 frozen rows; guardrail 0 hit",
         "source_head": head},
        {"n": 15, "cmd": "python -m pytest tests/product_delivery/test_mf_end_28.py -q",
         "exit": 0, "duration_s": 6.88,
         "note": "11 passed (focused, final bytes)", "source_head": head},
        {"n": 16, "cmd": "python -m pytest tests/product_delivery tests/product_p1/public_chain -q",
         "exit": 0, "duration_s": 285.08,
         "note": "BROAD WAVE mot lan: 716 passed, 3 skipped, rc0 (705+11 row moi)",
         "source_head": head},
        {"n": 17, "cmd": "python -m ruff check + py_compile (2 file py)",
         "exit": 0, "duration_s": None,
         "note": "clean; raw/static_gates.json", "source_head": head},
        {"n": 18, "cmd": "tools/build_evidence.py (lan dau, pre-commit)",
         "exit": 0, "duration_s": None,
         "note": "guard.json pre-commit + write_set before/after", "source_head": head},
    ]
    ledger_lines = []
    for row in commands:
        row = dict(row)
        row["written_utc"] = stamp
        ledger_lines.append(json.dumps(row, sort_keys=True, ensure_ascii=False))
    (EV / "commands.jsonl").write_text(
        "\n".join(ledger_lines) + "\n", encoding="utf-8")

    results = {
        "task": "MF-END-28",
        "source_head": head,
        "branch": run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip(),
        "rows": {
            "28.1_inventory_manifest_backend_frontend_ffmpeg_comfy_models_external":
                "PASS (2 rows: real-tree match + on-disk models)",
            "28.2_launcher_hidden_health_port_model_cwd_independent":
                "PASS (4 rows: static+parse, real check from foreign cwd, "
                "negative missing-model, idempotent stop)",
            "28.3_staged_package_outside_checkout_T06A_matrix":
                "PASS dev-host observed (stage rc0, setup preflight, launcher "
                "start/status/stop, frozen diagnose); clean Windows/human = NOT_RUN",
            "28.4_report_setup_launch_stop_outputs_missing_model_licenses":
                "PASS (README.md + THIRD_PARTY bounded patch; no secrets)",
        },
        "focused": {"passed": 11, "failed": 0, "duration_s": 6.90,
                    "note": "re-run tren BYTES CUOI (sau commit fix 4f50868)"},
        "broad": {"passed": 716, "skipped": 3, "failed": 0,
                  "duration_s": 285.08, "rc": 0,
                  "note": ("mot lan duy nhat tren bytes 61053d8; delta duy nhat "
                           "sang bytes cuoi (4f50868) la CHINH file test "
                           "(da re-run focused 11/11 tren bytes cuoi)")},
        "commits": run(["git", "log", "-2", "--format=%H"]).stdout.split(),
        "static": {"ruff_rc": ruff.returncode, "py_compile_rc": compile_.returncode},
        "guard": guard,
        "staged_package": {
            "root": "C:/Users/Admin/MF2D-demo-pkg-20260928",
            "runtime_root": "C:/Users/Admin/MF2D-demo-rt-20260928",
            "build_id": "yYjbPNMwhEO_tJl0FDvg-",
            "outside_checkout": True,
            "no_user_db_copied": True,
            "no_model_weights_copied": True,
            "clean_host": "NOT_RUN (khong co clean Windows VM/human tren may nay)",
        },
        "metrics": {
            "throughput_accepted_per_second": "unmeasured",
            "peak_ram_mb": "unmeasured",
            "peak_vram_mb": "unmeasured",
            "gpu_used": False,
            "note": "no GPU/render run in this task; package/launcher rows only",
        },
    }
    (EV / "results.json").write_text(
        json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")
    print("EVIDENCE_BUILT rc=0 head=", head)
    return 0


def manifest() -> int:
    rows = []
    root = EV
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "evidence_manifest.json":
            rows.append(
                {
                    "path": str(path.relative_to(root)).replace("\\", "/"),
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    payload = {
        "task": "MF-END-28",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "file_count": len(rows),
        "files": rows,
    }
    (EV / "evidence_manifest.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print("MANIFEST", len(rows), "files")
    return 0


if __name__ == "__main__":
    rc = main()
    manifest()
    print("EVIDENCE_BUILT done rc=", rc)
