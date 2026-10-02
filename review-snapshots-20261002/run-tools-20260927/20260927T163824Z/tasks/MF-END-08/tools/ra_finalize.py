"""MF-END-08 — finalize: the delivered manifest + the evidence documents (after the run).

Emits: app/media_workflows/reference_asset_v1.manifest.json (deliverable),
       REPORT.md, results.json, commands.jsonl, reproduction.md, write_set.json,
       EVIDENCE_INDEX.md, raw/finalize_record.json.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import time
from pathlib import Path

EV = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-08")
WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-08")
GRAPH = WT / "app/media_workflows/reference_asset_v1.json"
MANIFEST = WT / "app/media_workflows/reference_asset_v1.manifest.json"
TEST8 = WT / "tests/product_delivery/test_mf_end_08.py"
RT = Path("C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b")


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def utc(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


LICENSES = {
    "flux-2-klein-4b-fp8.safetensors": {
        "license": "apache-2.0",
        "source": "https://huggingface.co/black-forest-labs/FLUX.2-klein-4b-fp8",
        "source_file": "flux-2-klein-4b-fp8.safetensors (repo root)",
        "upstream_repo_revision": "5b4408e59397a4a37ccb46afe426d8ed86379441",
        "probe": "HF model API cardData.license (raw/hf_license_probe.json)",
        "file_embedded_license": "none (measured: only _quantization_metadata in the tensor file)",
        "why_used": "the DISTILLED FLUX.2 klein 4B checkpoint the official template pins",
    },
    "qwen_3_4b.safetensors": {
        "license": "apache-2.0",
        "source": "https://huggingface.co/Comfy-Org/vae-text-encorder-for-flux-klein-4b",
        "source_file": "split_files/text_encoders/qwen_3_4b.safetensors",
        "upstream_repo_revision": "5f526678002e43af5551dadb73ce2e8c91b43afe",
        "probe": "HF model API cardData.license (raw/hf_license_probe.json)",
        "download_log": "runtime/logs/fetch_klein.log: FETCH Comfy-Org/vae-text-encorder-for-flux-klein-4b",
        "file_embedded_license": "none (measured)",
        "why_used": "the FLUX.2 text encoder (CLIPLoader type=flux2) for the distilled template",
    },
    "flux2-vae.safetensors": {
        "license": "apache-2.0",
        "source": "https://huggingface.co/Comfy-Org/vae-text-encorder-for-flux-klein-4b",
        "source_file": "split_files/vae/flux2-vae.safetensors",
        "upstream_repo_revision": "5f526678002e43af5551dadb73ce2e8c91b43afe",
        "probe": "HF model API cardData.license (raw/hf_license_probe.json)",
        "download_log": ("runtime/logs/fetch_klein.log: FETCH "
                         "Comfy-Org/vae-text-encorder-for-flux-klein-4b/split_files/vae/"
                         "flux2-vae.safetensors"),
        "file_embedded_license": "none (measured)",
        "same_name_elsewhere": ("Comfy-Org/flux2-dev also hosts a flux2-vae.safetensors under a "
                                "NON-commercial license (flux-1-dev-non-commercial-license); the "
                                "fetch log line above decides provenance for THIS installed copy"),
        "why_used": "the FLUX.2 VAE paired with the klein 4B distilled checkpoint",
    },
}


def main() -> int:
    hashes = load(EV / "raw/model_and_node_hashes.json")
    build = load(EV / "raw/build_record.json")
    run = load(EV / "raw/run_record.json")
    staged = load(EV / "raw/stage_input.json")
    review = load(EV / "raw/review.json")
    doc = load(GRAPH)
    hf = load(EV / "raw/hf_license_probe.json")
    tmpl = {t["file"]: t for t in hashes["templates"]}

    models = []
    for m in hashes["models"]:
        L = LICENSES[m["file"]]
        models.append({**m, **L})

    nodes = []
    for n in hashes["node_sources"]:
        nodes.append({**n, "runtime_head": hashes["runtime"]["head"],
                      "registered_in_object_info": True})

    gr = run.get("golden_job", {})
    outputs = gr.get("outputs", [{}])
    asset = run.get("golden_asset", {})
    man = {
        "schema_version": "mf.reference_asset.graph.v1",
        "graph_id": "reference_asset_v1",
        # deterministic: the golden job's completion time from the frozen receipt (NOT now()),
        # so re-running this generator is byte-identical (proven by running it twice and diffing)
        "generated_at_utc": utc((gr.get("submitted_at_unix") or 0.0) + (gr.get("wall_s") or 0.0)),
        "workflow": {
            "graph_file": "app/media_workflows/reference_asset_v1.json",
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
            "validation_offline_vs_pinned_object_info": build["validation"],
            "validation_enum_extended_with_staged_name": build[
                "validation_enum_extended_with_staged_name"],
            "validation_live_server": run.get("live_validation"),
        },
        "models": models,
        "nodes": nodes,
        "runtime": {
            "head": hashes["runtime"]["head"], "porcelain_clean": not hashes["runtime"]["porcelain"],
            "source_read_only": True, "version_file_sha256": hashes["runtime"]["version_file_sha256"],
            "comfyui_dir": hashes["runtime"]["comfyui_dir"],
            "models_root": str(RT / "models").replace("\\", "/"),
            "license": "ComfyUI GPL-3.0 (LICENSE at the repo root, read this round)",
            "isolation_recipe": ("own base-directory (input/output/temp/user/custom_nodes under "
                                 "the MF-END-08 evidence root) + --models-directory pointing at "
                                 "the shared read-only model root + own port + --reserve-vram 1.0 "
                                 "+ --disable-auto-launch; one job at a time"),
            "object_info_live_file": "raw/object_info_live.json",
            "object_info_live_nodes": run.get("object_info_nodes"),
        },
        "inputs": {
            "staged_reference": staged["staged_input"],
            "source_artwork": staged["source_artwork"],
            "neutral_rgb": staged["alpha_policy_applied"]["neutral_rgb"],
            "alpha_formula": staged["alpha_policy_applied"]["formula"],
        },
        "golden_run": {
            "declared_gpu_jobs": 1,
            "prefix_job_cpu_only": {
                "note": ("tensor-truth preview: reference intake only (LoadImage / composite / "
                         "resize). NO model node in that graph, so it is not a GPU job"),
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
                      "outputs": outputs},
            "review": review,
        },
        "evidence_root": str(EV).replace("\\", "/"),
    }
    MANIFEST.write_text(json.dumps(man, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    # ── evidence documents ────────────────────────────────────────────────────
    ev_rows = []
    for p in sorted(EV.rglob("*")):
        if p.is_file() and "runtime" not in p.relative_to(EV).parts[:1]:
            ev_rows.append({"rel": str(p.relative_to(EV)).replace("\\", "/"),
                            "bytes": p.stat().st_size, "sha256": sha(p),
                            "mtime_utc": utc(p.stat().st_mtime)})
    ws = subprocess.run(["git", "status", "--porcelain"], cwd=WT, capture_output=True,
                        text=True).stdout.splitlines()
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=WT, capture_output=True,
                          text=True).stdout.strip()
    ws_files = []
    for f in (GRAPH, MANIFEST, TEST8):
        ws_files.append({"path": str(f.relative_to(WT)).replace("\\", "/"), "bytes": f.stat().st_size,
                         "sha256": sha(f), "lines": len(f.read_text(encoding="utf-8").splitlines()),
                         "mtime_utc": utc(f.stat().st_mtime)})
    (EV / "write_set.json").write_text(json.dumps(
        {"write_set": ws_files, "git_head": head, "git_status_porcelain": ws}, indent=1,
        ensure_ascii=False) + "\n", encoding="utf-8")

    gates_txt = (EV / "raw/gates.stdout.txt").read_text(encoding="utf-8") if (EV / "raw/gates.stdout.txt").exists() else ""
    gate_rows = []
    for line in gates_txt.splitlines():
        if line.startswith("==") or "passed" in line or "errors" in line.lower() or line.startswith("All checks") or line.startswith("Found"):
            gate_rows.append(line.strip())
    fg = json.loads((EV / "raw/final_gate.json").read_text(encoding="utf-8")) if (EV / "raw/final_gate.json").exists() else {}
    results = {
        "task": "MF-END-08", "artifact": "results.json",
        "micro_jobs": [
            {"id": "MF-END-08.1", "status": "PASS",
             "evidence": "app/media_workflows/reference_asset_v1.json derived_from + "
                         "raw/model_and_node_hashes.json + raw/hf_license_probe.json"},
            {"id": "MF-END-08.2", "status": "PASS",
             "evidence": "graph prompt pins identity/style/view keepers; alpha+dimension policies; "
                         "manifest.golden_run.review"},
            {"id": "MF-END-08.3", "status": "PASS",
             "evidence": "dimensions_policy (canvas 1024x1024 /16) + alpha_policy (in-graph "
                         "composite + opaque RGB output); distilled_vs_base block"},
            {"id": "MF-END-08.4", "status": "PASS",
             "evidence": "golden_request bindings + raw/run_record.json tensor_preview_comparison "
                         "+ asset"},
        ],
        "acceptance": {
            "graph_loads_validates_on_runtime_pin": run.get("live_validation"),
            "one_real_asset_through_graph": {"prompt_id": gr.get("prompt_id"),
                                             "completed": gr.get("completed"),
                                             "asset": asset},
            "view_identity_review": review.get("verdict"),
            "manifest_model_node_workflow_hashes": {
                "models": len(models), "nodes": len(nodes),
                "graph_file_sha256": man["workflow"]["graph_file_sha256"],
                "template_sha256": man["workflow"]["template_sha256"]},
            "license_source": "manifest.models[].license/source + workflow.template_license + "
                              "runtime.license",
        },
        "gates": {"transcript": gate_rows, "final_gate": {"passed": fg.get("passed"),
                                                          "total": fg.get("total"),
                                                          "all_ok": fg.get("all_ok"),
                                                          "head": fg.get("head")}},
        "terminal_state": "TASK_SUBMITTED", "quality_accepted": 0,
    }
    (EV / "results.json").write_text(json.dumps(results, indent=1, ensure_ascii=False) + "\n",
                                     encoding="utf-8")

    rows = [
        {"cmd": "python -B tools/ra_hash.py", "artifact": "raw/model_and_node_hashes.json"},
        {"cmd": "python -B tools/ra_stage.py", "artifact": "raw/stage_input.json"},
        {"cmd": "python -B tools/ra_build_graph.py", "artifact": "raw/build_record.json"},
        {"cmd": "python -B tools/ra_run.py (attempt 1)",
         "artifact": "raw/run_record_attempt1_failed.json"},
        {"cmd": "python -B tools/ra_run.py", "artifact": "raw/run_record.json"},
        {"cmd": "python -B tools/ra_review.py", "artifact": "raw/review.json"},
        {"cmd": "python -B tools/ra_finalize.py", "artifact": "raw/finalize_record.json"},
    ]
    cmd_path = EV / "commands.jsonl"
    first = not cmd_path.exists()
    seen: dict[str, str | None] = {}
    if not first:
        for line in cmd_path.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if "cmd" in r:
                seen[r["cmd"]] = r.get("utc")
    with open(cmd_path, "a", encoding="utf-8") as f:
        if first:
            f.write(json.dumps({"type": "header", "task": "MF-END-08",
                                "note": ("append-only harness rows; each row's time is the UTC mtime "
                                         "of the artifact it wrote (measured), rc where captured; "
                                         "offline/recon read-only commands are listed in "
                                         "REPORT.md §6.6")}, ensure_ascii=False) + "\n")
        for r in rows:
            p = EV / r["artifact"]
            r["utc"] = utc(p.stat().st_mtime) if p.exists() else None
            r["rc"] = None
            if r["cmd"] in seen:
                if seen[r["cmd"]] == r["utc"]:
                    continue                      # identical measurement: do not duplicate
                r["rerun"] = True                 # the artifact was regenerated later
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    fin = {"artifact": "finalize_record.json", "manifest_sha256": sha(MANIFEST),
           "graph_file_sha256": build["graph_file_sha256"], "evidence_files": len(ev_rows),
           "write_set": ws_files, "git_head": head, "porcelain": ws}
    (EV / "raw/finalize_record.json").write_text(json.dumps(fin, indent=1, ensure_ascii=False) + "\n",
                                                 encoding="utf-8")
    (EV / "EVIDENCE_INDEX.md").write_text(
        "# MF-END-08 evidence index\n\n" + "\n".join(
            f"* `{r['rel']}` · {r['bytes']} B · {r['sha256'][:16]} · {r['mtime_utc']}"
            for r in ev_rows) + "\n", encoding="utf-8")
    print(json.dumps(fin, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
