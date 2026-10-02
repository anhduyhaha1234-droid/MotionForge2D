"""MF-END-17 tool — final gate (pre-commit / post-commit).

Proves the exact TARGET checklist on the FINAL state:
  S1  the 4 write-set files exist at their exact paths
  S2  the 3 JSONs parse and the test file compiles
  S3  manifest.workflow.graph_file_sha256 == sha256(artifact bytes) and == its byte size
  S4  guard verify: CLEAN, 0 failures, 0 paths outside the allowlist
  S5  protected set: no drift vs the before snapshot
  S6  focused run: FOCUSED_EXIT=0 with 40 passed
  S7  static run: RUFF_EXIT=0 / PYCOMPILE_EXIT=0 / JSON_EXIT=0
  S8  broad wave (ONE run): BROAD_EXIT=0 with 350 passed, 3 skipped (310 baseline + 40)
  S9  evidence reverify: PASS, 0 mismatches, cross-links equal, both graph validations ok, ports refused
  S10 HF provenance: 3/3 files found, LFS oid == measured sha256, apache-2.0
  S11 model hashes: ok true, 3 files, the VACE unet matches the sealed MF-END-16 value
  S12 git: pre -> HEAD == base, porcelain == exactly the 4 allowlist paths; post -> HEAD^==base, porcelain empty
  S13 no push
  S14 terminal state: results.json TASK_SUBMITTED + quality_accepted 0 + no APPROVED/CLOSED; the
      artifact records the skip as a skip (SKIPPED_NOT_NEEDED, counts_as_test_pass false,
      skip_not_a_pass true, deliverable false, new_gpu_jobs_this_task 0)
  S15 profile patch: bounded-preimage record ok (before sha == the dispatch preimage 629f7a14...)
  S16 build determinism: both artifacts MATCH on rebuild
  S17 model area unchanged vs P0 + SCAIL probe BLOCKED_NO_WEIGHTS
  S18 no quality-acceptance claim anywhere in the delivered JSONs

Usage: python -B tools/w17_final_gate.py pre|post
"""

from __future__ import annotations

import hashlib
import json
import py_compile
import subprocess
import sys
import tempfile
import time
from pathlib import Path

WORKTREE = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-17")
RUN_ROOT = Path(__file__).resolve().parent.parent
RAW = RUN_ROOT / "raw"
BASE_COMMIT = "a2d7cc8f18a598ade29a24082fb6f30c55904de4"
BRANCH = "codex/mf-end-17-0928"

WRITE_SET = [
    "app/media_workflows/controlled_shot_v1.json",
    "app/media_workflows/controlled_shot_v1.manifest.json",
    "app/media_workflows/model_profiles.json",
    "tests/product_delivery/test_mf_end_17.py",
]
CORE_EVIDENCE = [
    "TARGET.md", "REPORT.md", "results.json", "reproduction.md",
    "raw/baseline_wave.stdout.txt", "raw/focused.stdout.txt", "raw/static.stdout.txt",
    "raw/broad_wave.stdout.txt", "raw/evidence_reverify.json", "raw/model_full_hashes.json",
    "raw/model_area_scan.json", "raw/scail_probe.json", "raw/hf_provenance_probe.json",
    "raw/build_record.json", "raw/determinism_check.json", "raw/profile_patch_record.json",
    "raw/write_set_guard_before.json", "raw/write_set_guard_post.json",
]


def git(args: list[str]) -> tuple[int, str]:
    p = subprocess.run(["git", *args], cwd=WORKTREE, capture_output=True, text=True, check=False)
    return p.returncode, p.stdout


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "pre"
    assert mode in ("pre", "post"), "usage: w17_final_gate.py pre|post"
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "result": "PASS" if ok else "FAIL", "detail": detail})

    # S1
    missing = [p for p in WRITE_SET if not (WORKTREE / p).is_file()]
    check("S1_write_set_files_exist", not missing, f"missing={missing}")

    # S2
    bad = []
    for p in WRITE_SET[:3]:
        try:
            load(WORKTREE / p)
        except Exception as err:  # noqa: BLE001
            bad.append(f"{p}: {err}")
    try:
        py_compile.compile(str(WORKTREE / WRITE_SET[3]), cfile=tempfile.mktemp(suffix=".pyc"), doraise=True)
    except Exception as err:  # noqa: BLE001
        bad.append(f"{WRITE_SET[3]}: {err}")
    check("S2_json_parse_and_compile", not bad, "; ".join(bad))

    # S3
    man = load(WORKTREE / WRITE_SET[1])
    art_path = WORKTREE / WRITE_SET[0]
    got = sha256_file(art_path)
    check("S3_manifest_binds_artifact_bytes",
          man["workflow"]["graph_file_sha256"] == got
          and man["workflow"]["graph_file_bytes"] == art_path.stat().st_size
          and man["workflow"]["shipped_runnable_graph"] is False,
          f"sha_match={man['workflow']['graph_file_sha256'] == got}")

    # S4 + S5
    post = load(RAW / "write_set_guard_post.json")
    before = load(RAW / "write_set_guard_before.json")
    check("S4_guard_post_clean",
          post["status"] == "CLEAN" and not post["failures"] and not post["outside_allowlist"],
          f"status={post['status']} failures={len(post['failures'])} outside={len(post['outside_allowlist'])}")
    bprot = {e["path"]: e.get("sha256") for e in before["protected"]}
    pprot = {e["path"]: e.get("sha256") for e in post["protected"]}
    drift = [k for k in bprot if bprot[k] != pprot.get(k)]
    check("S5_protected_no_drift", not drift, f"drift={drift}")

    # S6
    focused = (RAW / "focused.stdout.txt").read_text(encoding="utf-8", errors="replace")
    check("S6_focused_green", "40 passed" in focused and "FOCUSED_EXIT=0" in focused,
          focused.strip().splitlines()[-1][:80])

    # S7
    static = (RAW / "static.stdout.txt").read_text(encoding="utf-8", errors="replace")
    check("S7_static_green",
          "RUFF_EXIT=0" in static and "PYCOMPILE_EXIT=0" in static and "JSON_EXIT=0" in static)

    # S8
    broad = (RAW / "broad_wave.stdout.txt").read_text(encoding="utf-8", errors="replace")
    check("S8_broad_wave_once", "350 passed, 3 skipped" in broad and "BROAD_EXIT=0" in broad)

    # S9
    rv = load(RAW / "evidence_reverify.json")
    check("S9_reverify_pass",
          rv["verdict"] == "PASS" and rv["mismatches"] == 0 and rv["cross_links"]["all_equal"]
          and rv["graph_validation"]["p0_object_info"]["ok"] and rv["graph_validation"]["p3_object_info_gpu"]["ok"]
          and all(v == "refused" for v in rv["ports"].values()),
          f"rows={len(rv['rows'])} mismatches={rv['mismatches']}")

    # S10
    probe = load(RAW / "hf_provenance_probe.json")
    files_ok = all(f["exists"] and f["lfs_oid_equals_measured_sha256"] and f["size_matches_measured"]
                   for r in probe["repos"] for f in r["files"])
    licenses = {r["license"] for r in probe["repos"]}
    check("S10_hf_provenance", files_ok and licenses == {"apache-2.0"},
          f"files_ok={files_ok} licenses={licenses}")

    # S11
    mh = load(RAW / "model_full_hashes.json")
    sealed = next((f for f in mh["files"] if f["rel"].endswith("wan2.1_vace_14B_fp16.safetensors")), {})
    check("S11_model_full_hashes",
          mh["ok"] and len(mh["files"]) == 3 and sealed.get("sha_match_sealed") is True,
          f"files={len(mh['files'])} sealed_match={sealed.get('sha_match_sealed')}")

    # S12
    rc_head, head = git(["rev-parse", "HEAD"])
    head = head.strip()
    rc_status, status = git(["status", "--porcelain"])
    porcelain = [ln for ln in status.split("\n") if ln]
    if mode == "pre":
        paths = [ln[3:].strip().strip('"') for ln in porcelain]
        check("S12_git_pre_commit",
              head == BASE_COMMIT and sorted(paths) == sorted(WRITE_SET),
              f"head={head[:12]} porcelain={paths}")
    else:
        rc_parent, parent = git(["rev-parse", "HEAD^"])
        check("S12_git_post_commit",
              parent.strip() == BASE_COMMIT and porcelain == [],
              f"head={head[:12]} parent={parent.strip()[:12]} porcelain={len(porcelain)}")

    # S13 no push
    rc_up, up = git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
    has_upstream = rc_up == 0 and up.strip() != ""
    pushed = False
    if has_upstream:
        rc_contains, out = git(["branch", "-r", "--contains", head])
        pushed = rc_contains == 0 and out.strip() != ""
    check("S13_not_pushed", (not has_upstream) or (not pushed),
          f"upstream={up.strip() if has_upstream else None} pushed={pushed}")

    # S14 terminal state + the skip recorded as a skip
    results_path = RUN_ROOT / "results.json"
    art = load(art_path)
    act = art["activation"]
    if results_path.is_file():
        res = load(results_path)
        check("S14_terminal_state_and_skip_semantics",
              res.get("terminal_state") == "TASK_SUBMITTED"
              and res.get("quality_accepted") == 0
              and "APPROVED" not in json.dumps(res) and "CLOSED" not in json.dumps(res)
              and act["verdict"] == "SKIPPED_NOT_NEEDED"
              and act["counts_as_test_pass"] is False
              and art["claims"]["skip_not_a_pass"] is True
              and art["claims"]["deliverable"] is False
              and art["claims"]["new_gpu_jobs_this_task"] == 0,
              f"terminal={res.get('terminal_state')} verdict={act['verdict']}")
    else:
        check("S14_terminal_state_and_skip_semantics", False, "results.json missing")

    # S15 profile patch bounded-preimage record
    prec = load(RAW / "profile_patch_record.json")
    cur_sha = sha256_file(WORKTREE / WRITE_SET[2])
    check("S15_profile_patch_bounded",
          prec["invariants_ok"] is True
          and prec["before_sha256"] == "629f7a14f2fc9b38476e63a103195007bc2a78ba589e6b8551d0b8915c9b2df6"
          and prec["after_sha256"] == cur_sha
          and prec["grew_bytes"] > 0,
          f"before={prec['before_sha256'][:12]} after_ok={prec['after_sha256'] == cur_sha}")

    # S16 determinism
    det = load(RAW / "determinism_check.json")
    check("S16_build_deterministic",
          all(r["verdict"] == "MATCH" for r in det["results"]),
          str([r["verdict"] for r in det["results"]]))

    # S17 model area unchanged + scail probe
    area = load(RAW / "model_area_scan.json")
    sp = load(RAW / "scail_probe.json")
    check("S17_model_area_and_scail_probe",
          area["unchanged_vs_p0"] is True and area["file_count"] == 12
          and sp["verdict"] == "BLOCKED_NO_WEIGHTS" and sp["inference_tested"] == "NOT_RUN",
          f"area_files={area['file_count']} scail={sp['verdict']}")

    # S18 no quality-acceptance claim in the delivered JSONs
    blob = json.dumps(art, ensure_ascii=False) + json.dumps(man, ensure_ascii=False)
    prof = load(WORKTREE / WRITE_SET[2])
    check("S18_no_quality_acceptance_claim",
          '"quality_accepted": true' not in blob.lower()
          and prof["claims"]["quality_accepted"] is False
          and "APPROVED" not in json.dumps(prof) and "CLOSED" not in json.dumps(prof),
          "")

    failed = [c for c in checks if c["result"] == "FAIL"]
    out = {
        "artifact": f"final_gate_{mode}.json",
        "mode": mode,
        "at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "head": head,
        "branch": BRANCH,
        "checks": checks,
        "passed": len(checks) - len(failed),
        "total": len(checks),
        "verdict": "PASS" if not failed else "FAIL",
        "core_evidence_missing": [p for p in CORE_EVIDENCE if not (RUN_ROOT / p).exists()],
    }
    dest = RAW / f"final_gate_{mode}.json"
    dest.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"verdict": out["verdict"], "passed": out["passed"], "total": out["total"],
                      "failed": [c["check"] for c in failed],
                      "evidence_missing": out["core_evidence_missing"], "dest": str(dest)}))
    return 0 if out["verdict"] == "PASS" and not out["core_evidence_missing"] else 1


if __name__ == "__main__":
    sys.exit(main())
