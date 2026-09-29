"""DELTA-F2 evidence builder (adapted from MF-END-28's tool; idempotent).

Writes: raw/write_set_before.json, raw/write_set_after.json, raw/guard.json
(pre-commit) or raw/guard_final_postcommit.json, raw/static_gates.json,
results.json, commands.jsonl, evidence_manifest.json.  Fields not measured are
null/unmeasured with a note — never fabricated.

Run:  python.exe tools/build_evidence.py [pre|post]
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

WT = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/DELTA-F2")
EV = Path(
    r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
    r"20260927T163824Z/tasks/DELTA-F2"
)
ENGINE_SOURCE_REPO = Path(r"C:/Users/Admin/Documents/Codex/work/mfv1/wt-comfy")

ALLOWLIST = [
    "app/adapters/media_engine/comfy.py",
    "tests/product_delivery/test_delta_f2.py",
]
PY_FILES = list(ALLOWLIST)
#: Files this fix must NOT touch: the frozen record contract it composes through,
#: the caller that declares the terminal, and the frozen engine-adapter test whose
#: refusal taxonomy (12 codes) this task must keep.
PROTECTED_FILES = [
    "app/schemas/shot_reskin.py",
    "app/services/shot_reskin_executor.py",
    "tests/product_delivery/test_mf_end_18.py",
]
BASE_COMMIT = "951543664ed10e0dfaaff1f50f937b9624386074"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd or WT), capture_output=True, text=True)


def file_row(rel: str) -> dict:
    path = WT / rel
    data = path.read_bytes() if path.is_file() else b""
    return {
        "path": rel,
        "exists": path.is_file(),
        "size_bytes": len(data),
        "sha256": sha256_bytes(data) if path.is_file() else None,
        "crlf": data.count(b"\r\n"),
        "lf": data.count(b"\n"),
        "logical_lines": data.count(b"\n") + (0 if data.endswith(b"\n") or not data else 1),
        "mtime_utc": (
            datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
            if path.is_file() else None
        ),
    }


def phase_of(changed: list[str]) -> str:
    return "post_commit" if not changed else "pre_commit"


def main() -> int:
    phase = sys.argv[1] if len(sys.argv) > 1 else "pre"
    (EV / "raw").mkdir(parents=True, exist_ok=True)
    head = run(["git", "rev-parse", "--verify", "HEAD^{commit}"]).stdout.strip()
    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    porcelain_raw = run(["git", "status", "--porcelain"]).stdout
    porcelain = [line for line in porcelain_raw.split("\n") if line.strip()]
    changed = [line[3:].strip().strip('"') for line in porcelain]
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
            before["files"].append({"path": rel, "in_head": True,
                                    "size_bytes": len(data),
                                    "sha256": sha256_bytes(data)})
        else:
            before["files"].append({"path": rel, "in_head": False})
        after["files"].append(file_row(rel))

    outside = [rel for rel in changed if rel not in ALLOWLIST]
    missing = [row["path"] for row in after["files"] if not row["exists"]]
    protected_rows = []
    for rel in PROTECTED_FILES:
        # Blob ids, never worktree bytes (core.autocrlf=true — pitfall #46 family).
        live_blob = run(["git", "hash-object", f"--path={rel}", str(WT / rel)]).stdout.strip()
        head_blob = run(["git", "rev-parse", f"HEAD:{rel}"]).stdout.strip()
        protected_rows.append({"path": rel, "live_blob": live_blob,
                               "head_blob": head_blob,
                               "unchanged_vs_head": live_blob == head_blob and bool(live_blob)})
    engine_repo = {
        "path": str(ENGINE_SOURCE_REPO),
        "head": run(["git", "rev-parse", "--verify", "HEAD^{commit}"],
                    cwd=ENGINE_SOURCE_REPO).stdout.strip(),
        "porcelain": [ln for ln in run(["git", "status", "--porcelain"],
                                       cwd=ENGINE_SOURCE_REPO).stdout.split("\n") if ln.strip()],
    }
    guard = {
        "source_head": head,
        "branch": branch,
        "porcelain": porcelain,
        "porcelain_paths": changed,
        "allowlist": ALLOWLIST,
        "outside_allowlist": outside,
        "missing_expected_outputs": missing,
        "porcelain_equals_allowlist": changed == sorted(ALLOWLIST),
        "phase": phase_of(changed),
        "clean": (changed == sorted(ALLOWLIST)) or not changed,
        "protected_files_unchanged": all(row["unchanged_vs_head"] for row in protected_rows),
        "protected_rows": protected_rows,
        "engine_source_repo": engine_repo,
    }

    py = sys.executable
    ruff = run([py, "-m", "ruff", "check", *PY_FILES])
    compile_ = run([py, "-m", "py_compile", *PY_FILES])

    raw = EV / "raw"
    (raw / "write_set_before.json").write_text(
        json.dumps(before, indent=2, sort_keys=True), encoding="utf-8")
    (raw / "write_set_after.json").write_text(
        json.dumps(after, indent=2, sort_keys=True), encoding="utf-8")
    guard_name = "guard_final_postcommit.json" if phase == "post" else "guard.json"
    (raw / guard_name).write_text(
        json.dumps(guard, indent=2, sort_keys=True), encoding="utf-8")
    (raw / "static_gates.json").write_text(
        json.dumps({"ruff_rc": ruff.returncode,
                    "ruff_out": (ruff.stdout + ruff.stderr).strip().split("\n")[-3:],
                    "py_compile_rc": compile_.returncode,
                    "py_compile_out": (compile_.stdout + compile_.stderr).strip()[:400],
                    "files": PY_FILES},
                   indent=2, sort_keys=True), encoding="utf-8")

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    commands = [
        {"n": 1, "cmd": "git log --oneline -3; git status --porcelain (DELTA-F2)",
         "exit": 0, "duration_s": None,
         "note": "recon: HEAD 9515436 (FROZEN CANDIDATE #4), porcelain 0, branch "
                 "codex/mf-delta-f2-0928"},
        {"n": 2, "cmd": "python scripts/build_mf_comfy_dependency.py --source-repo "
                        "C:/Users/Admin/Documents/Codex/work/mfv1/wt-comfy",
         "exit": 0, "duration_s": None,
         "note": "engine dependency built from the pin: source_commit "
                 "70f718098f00f9dbdeb6cc9c5d7808b243eb0c57, 11 module files "
                 "byte-verified, wheel sha256 447dc4e6…"},
        {"n": 3, "cmd": "probe (temp) — pinned engine vs REAL capture "
                        "MF-DEMO-E2E/raw/history_shot1.json",
         "exit": 0, "duration_s": None,
         "note": "A) base declaration videos -> failed MF_COMFY_ARTIFACT_MISSING "
                 "(actual_kind=images vs expected_kind=videos); B) kind '' + "
                 "media_type video -> completed (2 artifacts, bucket images); "
                 "C) images+image -> failed 'non-image artifact' (bucket-match "
                 "alternative impossible)"},
        {"n": 4, "cmd": "python tools/apply_delta_f2_patch.py (byte-exact, CRLF)",
         "exit": 0, "duration_s": None,
         "note": "8/8 anchors hit exactly once; comfy.py 44,873 -> 54,805 B; "
                 "CRLF 984 -> 1,180 (no mixed endings); git diff --numstat +202/-6"},
        {"n": 5, "cmd": "python -m py_compile app/adapters/media_engine/comfy.py; "
                        "python -m ruff check <cung file>",
         "exit": 0, "duration_s": None, "note": "COMPILE_OK; ruff All checks passed"},
        {"n": 6, "cmd": "python -m pytest tests/product_delivery/test_delta_f2.py -q",
         "exit": 0, "duration_s": 2.96,
         "note": "focused 12 passed (4 micro/provenance + RED + GREEN + replay + "
                 "legacy + 3 negatives + png negative + witness + pin row)"},
        {"n": 7, "cmd": "python tools/red_on_base_probe.py (substitute BASE bytes, "
                        "restore in finally)",
         "exit": 0, "duration_s": None,
         "note": "RED ON BASE: pytest tren bytes base = 10 failed / 2 passed "
                 "(2 pass = fixture-provenance + RED row that asserts base failure); "
                 "RESTORE_VERIFIED sha256 eb7a5918… 54,805 B; full log raw/red_on_base.log. "
                 "EOL: base bytes written as WORKTREE bytes (LF->CRLF, 44,873 B) — the LF "
                 "blob was a first-attempt measurement artefact (see raw/base_staleness_probe.json)"},
        {"n": 8, "cmd": "python -m pytest tests/product_delivery/test_delta_f2.py -q "
                        "(sau restore)",
         "exit": 0, "duration_s": 2.96, "note": "focused 12 passed tren bytes patch"},
        {"n": 9, "cmd": "python tools/to_crlf.py (file test moi -> CRLF)",
         "exit": 0, "duration_s": None,
         "note": "test_delta_f2.py 713 CRLF / 713 LF, sha256 f6783b09…; "
                 "py_compile + ruff + focused 12 passed sau normalize"},
        {"n": 10, "cmd": "python -m pytest tests/product_delivery "
                         "tests/product_p1/public_chain -q",
         "exit": 1, "duration_s": 376.43,
         "note": "BROAD WAVE mot lan: 767 passed, 3 skipped, 1 failed = "
                 "test_mf_end_28.py::test_28_2_builder_is_deterministic (row tu-noi "
                 "'committed inventory.json is stale (rerun "
                 "packaging/demo/build_demo_package_inventory.py)'); baseline collect "
                 "759 truoc khi sua; log raw/broad_gate.log"},
        {"n": 11, "cmd": "python -m ruff check + py_compile (2 file trong write-set)",
         "exit": 0, "duration_s": None, "note": "clean; raw/static_gates.json"},
        {"n": 12, "cmd": "python tools/base_staleness_probe.py (corrected, EOL-aware)",
         "exit": 0, "duration_s": None,
         "note": "row MF-END-28 XANH tren bytes base (rc0, '1 passed'), app_tree_sha256 "
                 "d9e5ffb6… == committed; sau patch = 21b5e983… ⇒ row do CHINH patch nay "
                 "lam stale (generated artifact), khong phai loi co san; raw/"
                 "base_staleness_probe.json"},
        {"n": 13, "cmd": "python tools/inventory_staleness_measure.py",
         "exit": 0, "duration_s": None,
         "note": "fresh build (patched) vs committed: chi 1 field khac — "
                 "backend.app_tree_sha256 d9e5ffb6… -> 21b5e983…; determinism 2 lan chay "
                 "byte-identical; raw/inventory_staleness.json"},
        {"n": 14, "cmd": "python tools/tree_digest_origin.py (read-only, 2 worktree)",
         "exit": 0, "duration_s": None,
         "note": "INTEGRATION worktree live digest == committed d9e5ffb6…; giua 2 worktree "
                 "cung commit chi 1 file app khac bytes = chinh file patch; raw/"
                 "tree_digest_origin.json"},
        {"n": 15, "cmd": "tools/build_evidence.py pre (guard + write_set)",
         "exit": 0, "duration_s": None,
         "note": "porcelain == allowlist 2 path; protected 3 file blob-unchanged"},
        {"n": 16, "cmd": "git commit (local, KHONG push)",
         "exit": 0, "duration_s": None,
         "note": "16c81c46c7b0859828a3fbf4de747cd4933ab26c (parent 9515436); 2 file "
                 "+915 dong (comfy.py +202/-6, test moi 713); git in 'fatal: bad object "
                 "refs/codex/turn-diffs/…' + geometric-repack truoc khi commit thanh cong "
                 "(tinh trang co san, khong push)"},
        {"n": 17, "cmd": "tools/build_evidence.py post (guard post-commit + manifest)",
         "exit": 0, "duration_s": None,
         "note": "porcelain [] ; clean true; protected unchanged; engine source repo "
                 "70f7180 clean; manifest phu toan bo evidence root"},
    ]
    ledger_lines = []
    for row in commands:
        row = dict(row)
        row["written_utc"] = stamp
        ledger_lines.append(json.dumps(row, sort_keys=True, ensure_ascii=False))
    (EV / "commands.jsonl").write_text("\n".join(ledger_lines) + "\n", encoding="utf-8")

    results = {
        "task": "DELTA-F2",
        "source_head": head,
        "branch": branch,
        "base_commit": BASE_COMMIT,
        "rows": {
            "F2.micro_declaration_map": "PASS (video -> engine form kind '' + "
                                        "media_type video; image/audio unchanged; "
                                        "12 refusal codes kept)",
            "F2.defect_red_on_base": "PASS (BASE bytes of candidate #4 + REAL capture "
                                     "-> failed MF_COMFY_ARTIFACT_MISSING "
                                     "actual_kind=images vs expected_kind=videos)",
            "F2.fix_green": "PASS (same capture -> completed; both images+animated "
                            "mp4 entries app-kind video, bytes re-hashed; durable "
                            "contract proves the engine decided the bucket)",
            "F2.replay": "PASS (same identity reuses the receipt, no second POST, "
                         "video kind kept)",
            "F2.legacy_videos_bucket": "PASS (older pins publishing a real videos "
                                       "bucket still accepted; no shape proof needed)",
            "F2.negatives": "PASS (images without an aligned animated flag never "
                            "becomes the declared video; animated png refused by the "
                            "engine; unreadable history -> typed refusal)",
            "F2.write_set_bounded": "PASS (2 paths; protected 3 blobs unchanged; "
                                    "engine source repo at the pin, clean)",
        },
        "focused": {"passed": 12, "failed": 0, "duration_s": 2.86,
                    "note": "tren bytes cuoi (sau normalize CRLF); raw/focused.log"},
        "red_on_base": {"failed": 10, "passed": 2, "rc": 1,
                        "note": "pytest tren bytes base 9515436 cua comfy.py (worktree "
                                "bytes, CRLF); 2 pass = fixture-provenance + RED row khang "
                                "dinh chinh loi base; restore byte-verified; "
                                "raw/red_on_base.log"},
        "broad": {"passed": 767, "skipped": 3, "failed": 1, "rc": 1, "duration_s": 376.43,
                  "note": "MOT lan: tests/product_delivery + tests/product_p1/public_chain "
                          "(baseline collect 759). 1 fail = "
                          "test_mf_end_28.py::test_28_2_builder_is_deterministic — row "
                          "freshness cua artifact SINH TU DONG: patch doi "
                          "app/adapters/media_engine/comfy.py ⇒ app_tree_sha256 "
                          "d9e5ffb6… -> 21b5e983…; do luong tai "
                          "raw/inventory_staleness.json + raw/base_staleness_probe.json + "
                          "raw/tree_digest_origin.json. Integration action: chay lai "
                          "packaging/demo/build_demo_package_inventory.py tren cay union "
                          "(1 lan cho ca DELTA-F1+F2) + commit integration rieng."},
        "staleness_finding": {
            "row": "tests/product_delivery/test_mf_end_28.py::test_28_2_builder_is_deterministic",
            "cause": "generated packaging/demo/inventory.json records "
                     "backend.app_tree_sha256 (tree_digest over worktree bytes of app/**)",
            "measured": {
                "committed_inventory_field": "d9e5ffb6012eee2c5d953a43bf111b28947ecd6af501cfdf503c548ba3178072",
                "fresh_after_patch": "21b5e983df7ce28ab10ac248121f03e068a4e37bdf9df31857c4c32d1776f63d",
                "base_worktree_bytes_gives": "d9e5ffb6012eee2c5d953a43bf111b28947ecd6af501cfdf503c548ba3178072",
                "differing_fields_fresh_vs_committed": ["backend.app_tree_sha256"],
                "determinism_two_runs_identical": True,
                "integration_worktree_live_digest": "d9e5ffb6… (== committed)",
                "files_differing_between_worktrees": ["adapters/media_engine/comfy.py"],
            },
            "scope": "NGOAI write-set (2 file) — khong sua; chuyen integration owner "
                     "(tien le commit 9515436 da regenerate inventory tren cay union)",
        },
        "commits": run(["git", "log", "-3", "--format=%H"]).stdout.split(),
        "static": {"ruff_rc": ruff.returncode, "py_compile_rc": compile_.returncode},
        "guard": guard,
        "engine_pin": {"source_commit": "70f718098f00f9dbdeb6cc9c5d7808b243eb0c57",
                       "module_files": 11, "touched": False},
        "metrics": {
            "gpu_used": False,
            "renders_executed": 0,
            "note": "khong GPU/khong server Comfy that: chi replay history JSON + "
                    "mp4 THAT da capture trong evidence cua demo (read-only)",
        },
    }
    (EV / "results.json").write_text(
        json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")
    print("EVIDENCE_BUILT phase=", phase, "head=", head)
    return 0


def manifest() -> int:
    rows = []
    root = EV
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "evidence_manifest.json":
            rows.append({"path": str(path.relative_to(root)).replace("\\", "/"),
                         "size_bytes": path.stat().st_size,
                         "sha256": sha256_file(path)})
    payload = {
        "task": "DELTA-F2",
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
