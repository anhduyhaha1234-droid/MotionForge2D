"""MF-END-14 final gate — every checklist row measured on the REAL bytes, one JSON out.

usage: python sa_final_gate.py [pre|post]
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

EV = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-14")
WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-14")
GRAPH = WT / "app/media_workflows/shot_anchor_v1.json"
MANIFEST = WT / "app/media_workflows/shot_anchor_v1.manifest.json"
TEST14 = WT / "tests/product_delivery/test_mf_end_14.py"
BASE = "92ece7601a76557090554f70fa67200d5fc0cc83"
ALLOWLIST = {"app/media_workflows/shot_anchor_v1.json",
             "app/media_workflows/shot_anchor_v1.manifest.json",
             "tests/product_delivery/test_mf_end_14.py"}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run(cmd: list[str], cwd: Path, timeout: int = 300) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout + p.stderr)


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "pre"
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail[:400]})

    add("graph_file_exists", GRAPH.exists(), str(GRAPH))
    add("manifest_exists", MANIFEST.exists(), str(MANIFEST))
    add("test_file_exists", TEST14.exists(), str(TEST14))
    build = json.loads((EV / "raw/build_record.json").read_text(encoding="utf-8"))
    add("graph_matches_build_record", sha(GRAPH) == build["graph_file_sha256"],
        f"disk {sha(GRAPH)[:16]} vs build {build['graph_file_sha256'][:16]}")
    fin = json.loads((EV / "raw/finalize_record.json").read_text(encoding="utf-8"))
    add("manifest_matches_finalize_record", sha(MANIFEST) == fin["manifest_sha256"],
        f"disk {sha(MANIFEST)[:16]} vs finalize {fin['manifest_sha256'][:16]}")

    rc, out = run([sys.executable, "-m", "pytest",
                   "tests/product_delivery/test_mf_end_14.py", "-q"], WT, 300)
    add("focused_pytest_rc0", rc == 0, out.strip().splitlines()[-1] if out.strip() else "no out")
    rc, out = run([sys.executable, "-m", "ruff", "check",
                   "tests/product_delivery/test_mf_end_14.py"], WT, 120)
    add("ruff_rc0", rc == 0, out.strip().splitlines()[-1] if out.strip() else "no out")
    rc, out = run([sys.executable, "-m", "py_compile",
                   "tests/product_delivery/test_mf_end_14.py"], WT, 120)
    add("py_compile_rc0", rc == 0, out.strip() or "ok")

    guard = json.loads((EV / "raw/write_set_guard_post.json").read_text(encoding="utf-8"))
    add("guard_post_clean", guard["verdicts"]["clean"] is True,
        json.dumps(guard["verdicts"])[:300])

    bw = (EV / "raw/broad_wave.stdout.txt").read_text(encoding="utf-8")
    add("broad_wave_recorded", ("231 passed, 1 skipped" in bw and "30 passed, 2 skipped" in bw
                                and "rc=0" in bw and f"preimage_head={BASE}" in bw),
        " | ".join(ln for ln in bw.splitlines() if "passed" in ln or "rc=" in ln))

    run_rec = json.loads((EV / "raw/run_record.json").read_text(encoding="utf-8"))
    lv = run_rec.get("live_validation", {})
    add("live_object_info_validation_zero_errors",
        lv.get("errors") == [] and lv.get("warnings") == [] and lv.get("nodes") == 48,
        json.dumps(lv))
    px = run_rec.get("tensor_preview_comparison", {})
    add("tensor_preview_all_rows_match",
        len(px) == 7 and all(v.get("pixels_match_offline_expectation") is True
                             and v.get("file_sha256_matches_receipt") is True
                             for v in px.values()),
        f"{sum(1 for v in px.values() if v.get('pixels_match_offline_expectation'))}/{len(px)} "
        "pixel-equal + receipt-sha-verified")
    gr = run_rec.get("golden_job", {})
    asset = run_rec.get("golden_asset", {})
    add("golden_job_completed_asset_640x368",
        bool(gr.get("completed")) and asset.get("dims") == [640, 368]
        and len(asset.get("sha256", "")) == 64,
        f"prompt_id={gr.get('prompt_id')} wall_s={gr.get('wall_s')} "
        f"vram={run_rec.get('vram_peak_mib')} asset={asset.get('file')} "
        f"{asset.get('sha256', '')[:16]}")
    add("shutdown_post_stop_verified",
        run_rec.get("shutdown", {}).get("phase") == "POST_STOP_VERIFIED",
        json.dumps(run_rec.get("shutdown", {}))[:300])

    por = subprocess.run(["git", "status", "--porcelain"], cwd=WT, capture_output=True,
                         text=True).stdout.splitlines()
    paths = {ln[3:].strip().strip('"') for ln in por if ln.strip()}
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=WT, capture_output=True,
                          text=True).stdout.strip()
    if mode == "pre":
        add("porcelain_is_exactly_the_allowlist", paths == ALLOWLIST and head == BASE,
            f"head={head[:12]} paths={sorted(paths)}")
    else:
        log = subprocess.run(["git", "log", "--format=%H %s", "-3"], cwd=WT, capture_output=True,
                             text=True).stdout
        add("committed_clean_no_push",
            paths == set() and head != BASE and BASE in
            subprocess.run(["git", "rev-parse", f"{head}^"], cwd=WT, capture_output=True,
                           text=True).stdout.strip(),
            f"head={head[:12]} porcelain={sorted(paths)} log={log.splitlines()[:2]}")

    passed = sum(1 for c in checks if c["ok"])
    out = {"artifact": f"final_gate_{mode}.json", "mode": mode,
           "at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "head": head, "passed": passed, "total": len(checks),
           "all_ok": passed == len(checks), "checks": checks}
    p = EV / "raw" / f"final_gate_{mode}.json"
    p.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    for c in checks:
        print(("OK  " if c["ok"] else "FAIL") + f" {c['name']}: {c['detail']}")
    print(f"== {passed}/{len(checks)} ==")
    return 0 if out["all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
