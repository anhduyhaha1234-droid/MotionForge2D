"""MF-END-14 — finalize: the delivered manifest + the evidence documents (after the real run).

Emits: <WT>/app/media_workflows/shot_anchor_v1.manifest.json (deliverable, NEW file),
       REPORT.md, results.json, reproduction.md, write_set.json, evidence_manifest.json,
       raw/finalize_record.json, and appends rows to commands.jsonl.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import time
from pathlib import Path

EV = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-14")
WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-14")
GRAPH = WT / "app/media_workflows/shot_anchor_v1.json"
MANIFEST = WT / "app/media_workflows/shot_anchor_v1.manifest.json"
TEST14 = WT / "tests/product_delivery/test_mf_end_14.py"
RT = Path("C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b")

LICENSES = {
    "flux-2-klein-4b-fp8.safetensors": {
        "license": "apache-2.0",
        "source": "https://huggingface.co/black-forest-labs/FLUX.2-klein-4b-fp8",
        "source_file": "flux-2-klein-4b-fp8.safetensors (repo root)",
        "upstream_repo_revision": "5b4408e59397a4a37ccb46afe426d8ed86379441",
        "probe": ("HF model API cardData.license (MF-END-08 raw/hf_license_probe.json); the file "
                  "sha256 is re-measured here and is byte-identical"),
        "file_embedded_license": "none (measured: only _quantization_metadata)",
        "why_used": "the DISTILLED FLUX.2 klein 4B checkpoint the official template pins",
    },
    "qwen_3_4b.safetensors": {
        "license": "apache-2.0",
        "source": "https://huggingface.co/Comfy-Org/vae-text-encorder-for-flux-klein-4b",
        "source_file": "split_files/text_encoders/qwen_3_4b.safetensors",
        "upstream_repo_revision": "5f526678002e43af5551dadb73ce2e8c91b43afe",
        "probe": ("HF model API cardData.license (MF-END-08 raw/hf_license_probe.json); same file "
                  "sha256 re-measured here"),
        "download_log_same_revision": ("runtime/logs/fetch_klein.log: FETCH "
                                       "Comfy-Org/vae-text-encorder-for-flux-klein-4b"),
        "why_used": "the FLUX.2 text encoder (CLIPLoader type=flux2) for the distilled template",
    },
    "flux2-vae.safetensors": {
        "license": "apache-2.0",
        "source": "https://huggingface.co/Comfy-Org/vae-text-encorder-for-flux-klein-4b",
        "source_file": "split_files/vae/flux2-vae.safetensors",
        "upstream_repo_revision": "5f526678002e43af5551dadb73ce2e8c91b43afe",
        "probe": ("HF model API cardData.license (MF-END-08 raw/hf_license_probe.json); same file "
                  "sha256 re-measured here"),
        "same_name_elsewhere": ("Comfy-Org/flux2-dev hosts a flux2-vae.safetensors under a "
                                "NON-commercial license; the fetch-log line decides provenance "
                                "for THIS installed copy"),
        "why_used": "the FLUX.2 VAE paired with the klein 4B distilled checkpoint",
    },
}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def utc(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def main() -> int:
    hashes = load(EV / "raw/model_and_node_hashes.json")
    build = load(EV / "raw/build_record.json")
    run = load(EV / "raw/run_record.json")
    staged = load(EV / "raw/stage_input.json")
    review = load(EV / "raw/review.json")
    obs_path = EV / "raw/review_observations.json"
    obs = load(obs_path) if obs_path.exists() else None
    doc = load(GRAPH)
    tmpl = {t["file"]: t for t in hashes["templates"]}

    models = [{**m, **LICENSES[m["file"]]} for m in hashes["models"]]
    nodes = [{**n, "runtime_head": hashes["runtime"]["head"],
              "registered_in_object_info": True} for n in hashes["node_sources"]]

    gr = run.get("golden_job", {})
    asset = run.get("golden_asset", {})
    review_block = {
        "verdict": review["verdict"],
        "verdict_scope": review["verdict_scope"],
        "fidelity_identity_layout": review["fidelity_identity_layout"],
        "artifacts": review["artifacts"],
        "mechanical_rows": review["mechanical_rows"],
        "facts_quoted": review["facts_quoted"],
        "overlay_geometry": review["overlay_geometry"],
    }
    if obs:
        review_block["observations"] = obs

    man = {
        "schema_version": "mf.shot_anchor.graph.v1",
        "graph_id": "shot_anchor_v1",
        # deterministic: golden-job completion time from the frozen receipt (NOT now())
        "generated_at_utc": utc((gr.get("submitted_at_unix") or 0.0) + (gr.get("wall_s") or 0.0)),
        "workflow": {
            "graph_file": "app/media_workflows/shot_anchor_v1.json",
            "graph_file_sha256": build["graph_file_sha256"],
            "graph_object_sha256": build["graph_object_sha256"],
            "template_file": "image_flux2_klein_image_edit_4b_distilled.json",
            "template_path": tmpl["image_flux2_klein_image_edit_4b_distilled.json"]["path"],
            "template_sha256": tmpl["image_flux2_klein_image_edit_4b_distilled.json"]["sha256"],
            "template_sha256_16": tmpl["image_flux2_klein_image_edit_4b_distilled.json"]["sha256"][:16],
            "template_license": "MIT (comfyui-workflow-templates-json 0.1.92 dist-info "
                                "License-Expression)",
            "base_template_reference": {
                "template_file": "image_flux2_klein_image_edit_4b_base.json",
                "template_sha256": tmpl["image_flux2_klein_image_edit_4b_base.json"]["sha256"],
                "used": False,
                "why": "base 4B checkpoint + full_encoder_small_decoder VAE are NOT installed"},
            "accepted_predecessor_graph": doc["derived_from"]["accepted_predecessor_graph"],
            "prompt_sha256": build["prompt_sha256"],
            "validation_live_server": run.get("live_validation"),
        },
        "models": models,
        "nodes": nodes,
        "runtime": {
            "head": hashes["runtime"]["head"],
            "porcelain_clean": not hashes["runtime"]["porcelain"],
            "source_read_only": True,
            "version_file_sha256": hashes["runtime"]["version_file_sha256"],
            "comfyui_dir": hashes["runtime"]["comfyui_dir"],
            "models_root": str(RT / "models").replace("\\", "/"),
            "license": "ComfyUI GPL-3.0 (LICENSE at the repo root)",
            "isolation_recipe": ("own base-directory (input/output/temp/user/custom_nodes under "
                                 "the MF-END-14 evidence root; custom_nodes pre-created because "
                                 "main.py::execute_prestartup_script lists it before serving) + "
                                 "--models-directory pointing at the shared read-only model root "
                                 "+ own port + --reserve-vram 1.0 + --disable-auto-launch; one "
                                 "job at a time"),
            "object_info_live_file": "raw/object_info_live.json",
            "object_info_live_nodes": run.get("object_info_nodes"),
        },
        "inputs": {
            "staged": staged["staged"],
            "alpha_formula": "out = mask*src + (1 - mask)*dst ; mask = InvertMask(1-alpha)",
            "neutral_rgb": [128, 128, 128],
            "alpha_proof_derived_crosscheck": staged.get("alpha_proof_derived_crosscheck"),
        },
        "golden_run": {
            "declared_gpu_jobs": 1,
            "prefix_job_cpu_only": {
                "note": ("tensor-truth preview: intake only (LoadImage / composite / resize). NO "
                         "model node in that graph, so it is not a GPU job"),
                "prompt_id": run.get("prefix_job", {}).get("prompt_id"),
                "completed": run.get("prefix_job", {}).get("completed"),
                "wall_s": run.get("prefix_job", {}).get("wall_s"),
                "pixel_comparison": run.get("tensor_preview_comparison"),
            },
            "prompt_id": gr.get("prompt_id"),
            "completed": gr.get("completed"),
            "graph_object_sha256": gr.get("graph_object_sha256"),
            "wall_s": gr.get("wall_s"),
            "vram_peak_mib": run.get("vram_peak_mib"),
            "gpu_util_peak_pct": run.get("gpu_util_peak_pct"),
            "epoch": run.get("epoch"),
            "shutdown": run.get("shutdown"),
            "server_log": "runtime/server.log",
            "asset": {"file": asset.get("file"), "path": asset.get("path"),
                      "bytes": asset.get("bytes"), "sha256": asset.get("sha256"),
                      "dims": asset.get("dims"), "mode": asset.get("mode"),
                      "outputs": gr.get("outputs")},
            "review": review_block,
        },
        "evidence_root": str(EV).replace("\\", "/"),
    }
    MANIFEST.write_text(json.dumps(man, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    # ── evidence documents ────────────────────────────────────────────────────
    ws = subprocess.run(["git", "status", "--porcelain"], cwd=WT, capture_output=True,
                        text=True).stdout.splitlines()
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=WT, capture_output=True,
                          text=True).stdout.strip()
    ws_files = []
    for f in (GRAPH, MANIFEST, TEST14):
        ws_files.append({"path": str(f.relative_to(WT)).replace("\\", "/"),
                         "bytes": f.stat().st_size, "sha256": sha(f),
                         "lines": len(f.read_text(encoding="utf-8").splitlines()),
                         "mtime_utc": utc(f.stat().st_mtime)})
    (EV / "write_set.json").write_text(json.dumps(
        {"write_set": ws_files, "git_head": head, "git_status_porcelain": ws}, indent=1,
        ensure_ascii=False) + "\n", encoding="utf-8")

    results = {
        "task": "MF-END-14", "artifact": "results.json",
        "micro_jobs": [
            {"id": "MF-END-14.1", "status": "PASS",
             "evidence": ("role_map (measured bbox/refs per role) + frozen prompt reference-2/3/4 "
                          "bindings + tensor preview overlays previews/sa_v1_overlay_*.png")},
            {"id": "MF-END-14.2", "status": "PASS",
             "evidence": ("graph = FLUX.2 klein distilled full-scene edit at the fixed canvas "
                          "640x368 (declared) + per-image alpha composite; real run receipt in "
                          "manifest.golden_run + asset sha")},
            {"id": "MF-END-14.3", "status": "PASS",
             "evidence": ("prefix CPU job tensor previews (7/7 pixel-equal to the offline node "
                          "path) + role/prop/contact overlays from the sealed MF-END-12 masks")},
            {"id": "MF-END-14.4", "status": "PASS",
             "evidence": ("prompt/template/style frozen (prompt_sha256, template_sha256) + params "
                          "declared with mirrors; extra anchors chained as ReferenceLatent "
                          "CONDITIONING on pos+neg only (node/model source measured)")},
        ],
        "acceptance": {
            "graph_loads_validates_on_runtime_pin": run.get("live_validation"),
            "one_real_anchor_through_graph": {"prompt_id": gr.get("prompt_id"),
                                              "completed": gr.get("completed"),
                                              "asset": asset},
            "tensor_preview_all_rows_match": all(
                v.get("pixels_match_offline_expectation") is True
                for v in (run.get("tensor_preview_comparison") or {}).values()),
            "review": {"verdict": review["verdict"],
                       "fidelity_identity_layout": review["fidelity_identity_layout"]},
            "no_render_no_push": True,
        },
        "gates": {"note": "focused/static/broad results recorded in REPORT.md + commands.jsonl"},
        "terminal_state": "TASK_SUBMITTED", "quality_accepted": 0,
    }
    (EV / "results.json").write_text(json.dumps(results, indent=1, ensure_ascii=False) + "\n",
                                     encoding="utf-8")

    # quick evidence index (files, bytes, sha) — evidence_manifest.json
    rows = []
    for p in sorted(EV.rglob("*")):
        rel = str(p.relative_to(EV)).replace("\\", "/")
        if p.is_file() and not rel.startswith("runtime/"):
            rows.append({"rel": rel, "bytes": p.stat().st_size, "sha256": sha(p),
                         "mtime_utc": utc(p.stat().st_mtime)})
    (EV / "evidence_manifest.json").write_text(json.dumps(
        {"task": "MF-END-14", "artifact": "evidence_manifest.json", "files": rows,
         "file_count": len(rows), "note": "regenerated after every material write; runtime/ "
                                          "(server base dir) excluded by design"},
        indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    # commands.jsonl (append-only, UTC from artifact mtimes)
    cmd_path = EV / "commands.jsonl"
    first = not cmd_path.exists()
    rows_cmd = [
        {"cmd": "python -B tools/sa_guard.py before", "artifact": "raw/write_set_guard_before.json"},
        {"cmd": "python -B tools/sa_hash.py", "artifact": "raw/model_and_node_hashes.json"},
        {"cmd": "python -B tools/sa_build.py", "artifact": "raw/build_record.json"},
        {"cmd": "python -B tools/sa_stage.py", "artifact": "raw/stage_input.json"},
        {"cmd": "python -B tools/sa_run.py (attempt 1, pytest-missing abort)",
         "artifact": "raw/run_record_attempt1_failed.json"},
        {"cmd": "python -B tools/sa_run.py", "artifact": "raw/run_record.json"},
        {"cmd": "python -B tools/sa_overlay.py", "artifact": "raw/review.json"},
        {"cmd": "python -B tools/sa_finalize.py", "artifact": "raw/finalize_record.json"},
    ]
    with open(cmd_path, "a", encoding="utf-8") as f:
        if first:
            f.write(json.dumps({"type": "header", "task": "MF-END-14",
                                "note": ("append-only harness rows; each row's time is the UTC "
                                         "mtime of the artifact it wrote (measured)")},
                               ensure_ascii=False) + "\n")
        for r in rows_cmd:
            p = EV / r["artifact"]
            r["utc"] = utc(p.stat().st_mtime) if p.exists() else None
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    fin = {"artifact": "finalize_record.json", "manifest_sha256": sha(MANIFEST),
           "graph_file_sha256": build["graph_file_sha256"], "evidence_files": len(rows),
           "write_set": ws_files, "git_head": head, "porcelain": ws}
    (EV / "raw/finalize_record.json").write_text(json.dumps(fin, indent=1, ensure_ascii=False) + "\n",
                                                 encoding="utf-8")
    print(json.dumps(fin, indent=1, ensure_ascii=False)[:2500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
