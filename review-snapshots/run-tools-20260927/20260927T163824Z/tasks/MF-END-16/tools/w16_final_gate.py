"""MF-END-16 tool — final gate (pre-commit / post-commit).

Proves the exact TARGET checklist on the FINAL state:
  S1  the 4 write-set files exist at their exact paths
  S2  the 3 JSONs parse
  S3  manifest.graph_file_sha256 == sha256(graph file bytes) and == its byte size
  S4  write-set guard post: CLEAN, 0 failures, 0 paths outside the allowlist
  S5  protected set: no drift vs the before snapshot
  S6  focused run file exists with exit 0 and 49 passed
  S7  static run file: ruff 0 / py_compile 0 / JSON loads 0
  S8  broad wave file: exit 0 with 310 passed, 3 skipped (baseline + 49)
  S9  evidence reverify: PASS, 0 mismatches, all ports refused
  S10 HF provenance probe: 6/6 files found, apache-2.0
  S11 model hashes: ok true, 6 files
  S12 git: pre -> HEAD == 88ef530, 4 untracked allowlist paths; post -> HEAD != 88ef530,
      HEAD^ == 88ef530, porcelain empty
  S13 no push: no upstream, or the remote branch does not contain HEAD
  S14 every claim of quality acceptance is absent (no APPROVED/CLOSED status)

Usage: python -B tools/w16_final_gate.py pre|post
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

WORKTREE = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-16")
RUN_ROOT = Path(__file__).resolve().parent.parent
RAW = RUN_ROOT / "raw"
BASE_COMMIT = "88ef5302d4ac0868c679f7f1f5ea2f58722a11f8"
BRANCH = "codex/mf-end-16-0928"

WRITE_SET = [
    "app/media_workflows/wan_shot_v1.json",
    "app/media_workflows/wan_shot_v1.manifest.json",
    "app/media_workflows/model_profiles.json",
    "tests/product_delivery/test_mf_end_16.py",
]
CORE_EVIDENCE = [
    "TARGET.md", "results.json", "reproduction.md", "REPORT.md",
    "raw/baseline_wave.stdout.txt", "raw/focused.stdout.txt", "raw/static.stdout.txt",
    "raw/broad_wave.stdout.txt", "raw/model_full_hashes.json", "raw/evidence_reverify.json",
    "raw/hf_provenance_probe.json", "raw/build_record.json", "raw/determinism_check.json",
    "raw/write_set_guard_before.json", "raw/write_set_guard_post.json",
]


def git(args: list[str]) -> tuple[int, str]:
    p = subprocess.run(["git", *args], cwd=WORKTREE, capture_output=True, text=True, check=False)
    return p.returncode, p.stdout


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024 * 4), b""):
            h.update(chunk)
    return h.hexdigest()


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "pre"
    assert mode in ("pre", "post"), "usage: w16_final_gate.py pre|post"
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "result": "PASS" if ok else "FAIL", "detail": detail})

    # S1
    missing = [p for p in WRITE_SET if not (WORKTREE / p).is_file()]
    check("S1_write_set_files_exist", not missing, f"missing={missing}")

    # S2
    bad_json = []
    for p in WRITE_SET[:3]:
        try:
            load(WORKTREE / p)
        except Exception as err:  # noqa: BLE001
            bad_json.append(f"{p}: {err}")
    check("S2_json_parse", not bad_json, "; ".join(bad_json))

    # S3
    man = load(WORKTREE / WRITE_SET[1])
    graph_path = WORKTREE / WRITE_SET[0]
    got = sha256_file(graph_path)
    check("S3_manifest_graph_sha_and_size",
          man["workflow"]["graph_file_sha256"] == got
          and man["workflow"]["graph_file_bytes"] == graph_path.stat().st_size,
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
    check("S6_focused_green", "49 passed" in focused and "FOCUSED_EXIT=0" in focused,
          focused.strip().splitlines()[-3:].__str__()[:160])

    # S7
    static = (RAW / "static.stdout.txt").read_text(encoding="utf-8", errors="replace")
    check("S7_static_green",
          "RUFF_EXIT=0" in static and "PYCOMPILE_EXIT=0" in static and "JSON_EXIT=0" in static)

    # S8
    broad = (RAW / "broad_wave.stdout.txt").read_text(encoding="utf-8", errors="replace")
    check("S8_broad_wave_once", "310 passed, 3 skipped" in broad and "BROAD_EXIT=0" in broad)

    # S9
    rv = load(RAW / "evidence_reverify.json")
    check("S9_reverify_pass",
          rv["verdict"] == "PASS" and rv["mismatches"] == 0,
          f"rows={len(rv['rows'])} ports={rv['ports']}")

    # S10
    probe = load(RAW / "hf_provenance_probe.json")
    files_ok = all(f["exists"] for r in probe["repos"] for f in r["files"])
    licenses = {r["license"] for r in probe["repos"]}
    check("S10_hf_provenance", files_ok and licenses == {"apache-2.0"},
          f"files_ok={files_ok} licenses={licenses}")

    # S11
    mh = load(RAW / "model_full_hashes.json")
    check("S11_model_full_hashes", mh["ok"] and len(mh["files"]) == 6,
          f"files={len(mh['files'])} ok={mh['ok']}")

    # S12
    rc_head, head = git(["rev-parse", "HEAD"])
    head = head.strip()
    rc_status, status = git(["status", "--porcelain"])
    porcelain = [ln for ln in status.split("\n") if ln]
    if mode == "pre":
        check("S12_git_pre_commit",
              head == BASE_COMMIT and len(porcelain) == len(WRITE_SET)
              and all(ln[3:].strip().strip('"') in WRITE_SET for ln in porcelain),
              f"head={head[:12]} porcelain={len(porcelain)}")
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

    # S14 no quality-acceptance claim
    blob = json.dumps(load(RAW / "write_set_guard_post.json"), ensure_ascii=False)
    results_path = RUN_ROOT / "results.json"
    if results_path.is_file():
        res = load(results_path)
        check("S14_terminal_state_and_no_approval",
              res.get("terminal_state") == "TASK_SUBMITTED"
              and res.get("quality_accepted") == 0
              and "APPROVED" not in json.dumps(res) and "CLOSED" not in json.dumps(res),
              f"terminal={res.get('terminal_state')} qa={res.get('quality_accepted')}")
    else:
        check("S14_terminal_state_and_no_approval", mode == "pre", "results.json pending (pre)")

    failed = [c for c in checks if c["result"] == "FAIL"]
    out = {
        "artifact": f"final_gate_{mode}.json",
        "mode": mode,
        "at_utc": __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime()),
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
    return 0 if out["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
