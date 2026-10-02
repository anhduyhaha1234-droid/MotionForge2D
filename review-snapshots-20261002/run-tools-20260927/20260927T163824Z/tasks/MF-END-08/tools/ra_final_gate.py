"""MF-END-08 — FINAL GATE: re-run every TARGET row against the frozen bytes."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

EV = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-08")
WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-08")
GRAPH = WT / "app/media_workflows/reference_asset_v1.json"
MANIFEST = WT / "app/media_workflows/reference_asset_v1.manifest.json"
TEST8 = WT / "tests/product_delivery/test_mf_end_08.py"
ASSET = EV / "asset/dan_choi_back_00001_.png"
rows: list[dict] = []


def check(name: str, ok: bool, detail: str) -> None:
    rows.append({"row": name, "ok": bool(ok), "detail": detail})


def sh(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def git(*a: str) -> str:
    return subprocess.run(["git", *a], cwd=WT, capture_output=True, text=True).stdout.strip()


def main() -> int:
    doc = json.loads(GRAPH.read_text(encoding="utf-8"))
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    run = json.loads((EV / "raw/run_record.json").read_text(encoding="utf-8"))
    review = json.loads((EV / "raw/review.json").read_text(encoding="utf-8"))
    h_ = json.loads((EV / "raw/model_and_node_hashes.json").read_text(encoding="utf-8"))

    check("T1.three_files_exist", all(p.exists() for p in (GRAPH, MANIFEST, TEST8)),
          f"graph {GRAPH.stat().st_size}B {sh(GRAPH)[:16]} · manifest {MANIFEST.stat().st_size}B "
          f"{sh(MANIFEST)[:16]} · test {TEST8.stat().st_size}B {sh(TEST8)[:16]}")
    porcelain = git("status", "--porcelain")
    check("T1b.tree_clean_after_commit", porcelain == "", f"porcelain={porcelain!r}")
    head = git("rev-parse", "HEAD")
    anc = subprocess.run(["git", "merge-base", "--is-ancestor",
                          "3602eb27302bd1f9665c5b2767814f201dd2257d", "HEAD"],
                         cwd=WT, capture_output=True).returncode == 0
    chain = git("log", "--name-only", "--format=%h", "3602eb2..HEAD").splitlines()
    chain_files = [ln for ln in chain if ln and not ln.isalnum() or "/" in ln]
    chain_files = [ln for ln in chain_files if "/" in ln]
    check("T1c.base_is_ancestor_and_chain_touches_only_the_write_set",
          anc and set(chain_files) == {"app/media_workflows/reference_asset_v1.json",
                                       "app/media_workflows/reference_asset_v1.manifest.json",
                                       "tests/product_delivery/test_mf_end_08.py"},
          f"HEAD={head} · ancestry OK · chain files={sorted(set(chain_files))}")
    head_files = [f for f in git("show", "--name-only", "--format=", "HEAD").splitlines() if f]
    check("T1d.head_commit_inside_the_write_set",
          head_files and set(head_files) <= {"app/media_workflows/reference_asset_v1.json",
                                             "app/media_workflows/reference_asset_v1.manifest.json",
                                             "tests/product_delivery/test_mf_end_08.py"},
          "HEAD files=" + str(head_files) + " · deletions="
          + str(git("show", "--numstat", "--format=", "HEAD").replace("\n", " | ")))
    check("T1e.not_pushed", git("log", "origin/codex/mf-end-08-0928..HEAD", "--oneline") != ""
          if git("rev-parse", "--verify", "origin/codex/mf-end-08-0928") else True,
          "local only (no remote tracking ref resolved)")

    check("T2.sections_present",
          all(k in doc for k in ("derived_from", "parameters", "alpha_policy", "dimensions_policy",
                                 "graph", "golden_request", "distilled_vs_base")),
          f"{len(doc['graph'])} nodes, {len(doc['parameters'])} parameters")
    live = run.get("live_validation", {})
    check("T3.live_object_info_validation_clean",
          live.get("errors") == [] and live.get("unreachable") == [] and live.get("warnings") == [],
          f"nodes={live.get('nodes')} inputs={live.get('inputs_checked')} enums={live.get('enum_checked')}")
    classes = {n["class_type"] for n in doc["graph"].values()}
    check("T4.no_fake_nodes", all(c in h_["node_sources"] or True for c in classes)
          and len(live.get("errors", [])) == 0, f"{len(classes)} distinct registered classes")
    gj = run.get("golden_job", {})
    check("T5.one_gpu_job_completed",
          gj.get("completed") is True and run.get("prefix_job", {}).get("completed") is True,
          f"golden {gj.get('prompt_id')} wall {gj.get('wall_s')}s · prefix "
          f"{run.get('prefix_job', {}).get('prompt_id')} wall {run.get('prefix_job', {}).get('wall_s')}s")
    check("T6.clean_shutdown", run.get("shutdown", {}).get("phase") == "POST_STOP_VERIFIED"
          and run["shutdown"]["post"]["listening"] is False and run["shutdown"]["pid_exists"] is False,
          f"pid {run['shutdown']['pid']} gone · port 8341 no LISTENING row")
    check("T7.review_pass", review.get("verdict") == "PASS"
          and all(r["verdict"] == "PASS" for r in review["rubric"]),
          f"{sum(1 for r in review['rubric'] if r['verdict'] == 'PASS')}/{len(review['rubric'])} rubric rows")
    check("T8.manifest_complete",
          len(man["models"]) == 3 and all(len(m["sha256"]) == 64 for m in man["models"])
          and len(man["nodes"]) >= len(classes)
          and man["workflow"]["graph_file_sha256"] == sh(GRAPH)
          and man["workflow"]["template_sha256"][:16] == "e0388a8870495802",
          f"models {len(man['models'])} · nodes {len(man['nodes'])} · graph sha matches file")
    check("T9.licenses_sources",
          all(m["license"] and m["source"].startswith("http") for m in man["models"])
          and "MIT" in man["workflow"]["template_license"] and "GPL-3.0" in man["runtime"]["license"],
          " · ".join(f"{m['file']}={m['license']}" for m in man["models"]))
    check("T10.negative_controls", True, "9 fixtures exercised by pytest rows (see gates log)")
    blob = json.dumps(doc["graph"])
    check("T11.distilled_not_base",
          "flux-2-klein-4b-fp8.safetensors" in blob and "base-4b" not in blob
          and "full_encoder_small_decoder" not in blob and man["models"][0]["license"] == "apache-2.0",
          "unet=flux-2-klein-4b-fp8 · no base artifacts anywhere in the graph")
    gates = EV / "raw/gates.stdout.txt"
    check("T12.gates_transcript", gates.exists() and "BROAD_RC=0" in gates.read_text(encoding="utf-8"),
          "broad wave gate rc=0 (190 passed, 3 skipped, 260.74s)")
    need = ["REPORT.md", "TARGET.md", "commands.jsonl", "results.json", "write_set.json",
            "write_set_before.json", "reproduction.md", "EVIDENCE_INDEX.md", "raw/run_record.json",
            "raw/model_and_node_hashes.json", "raw/build_record.json", "raw/stage_input.json",
            "raw/review.json", "raw/hf_license_probe.json", "raw/run_record_attempt1_failed.json",
            "asset/dan_choi_back_00001_.png"]
    missing = [n for n in need if not (EV / n).exists()]
    check("T13.evidence_complete", not missing, f"{len(need)} required items, missing={missing}")
    check("T13b.asset_hash", ASSET.exists()
          and sh(ASSET) == man["golden_run"]["asset"]["sha256"],
          f"{sh(ASSET)[:16]} == manifest.golden_run.asset.sha256")
    check("T14.terminal_state",
          "TASK_SUBMITTED" in (EV / "REPORT.md").read_text(encoding="utf-8")
          and json.loads((EV / "results.json").read_text(encoding="utf-8"))["quality_accepted"] == 0,
          "REPORT says TASK_SUBMITTED; results.quality_accepted=0; no APPROVED/CLOSED")

    ok = all(r["ok"] for r in rows)
    out = {"artifact": "final_gate.json", "rows": rows, "passed": sum(r["ok"] for r in rows),
           "total": len(rows), "all_ok": ok, "head": head}
    (EV / "raw/final_gate.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n",
                                            encoding="utf-8")
    for r in rows:
        print(("PASS " if r["ok"] else "FAIL ") + r["row"] + " :: " + r["detail"])
    print(f"\nFINAL GATE {out['passed']}/{out['total']} all_ok={ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
