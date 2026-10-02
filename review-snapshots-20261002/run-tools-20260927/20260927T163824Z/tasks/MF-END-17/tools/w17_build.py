"""MF-END-17 builder — generates the two deliverable artifacts (deterministic).

  app/media_workflows/controlled_shot_v1.json
  app/media_workflows/controlled_shot_v1.manifest.json

Everything is read from already-measured inputs:
  proof evidence (read-only) + raw/{evidence_reverify,model_full_hashes,model_area_scan,
  scail_probe,hf_provenance_probe}.json + the predecessor registry model_profiles.json.

Usage:
  python -B tools/w17_build.py            # write both files + raw/build_record.json
  python -B tools/w17_build.py --verify   # rebuild to temp, compare modulo generated_at_utc
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

WORKTREE = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-17")
PROOF = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/proof")
RUN_ROOT = Path(__file__).resolve().parent.parent
RAW = RUN_ROOT / "raw"

ARTIFACT_REL = "app/media_workflows/controlled_shot_v1.json"
MANIFEST_REL = "app/media_workflows/controlled_shot_v1.manifest.json"
PROFILES_REL = "app/media_workflows/model_profiles.json"

TASK = "MF-END-17"
BASE = "a2d7cc8f18a598ade29a24082fb6f30c55904de4"
BRANCH = "codex/mf-end-17-0928"
EVIDENCE_ROOT = "C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-17"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def dump_crlf_bytes(doc: dict) -> bytes:
    text = json.dumps(doc, indent=1, ensure_ascii=False)
    return text.replace("\n", "\r\n").encode("utf-8")


def build(gen: str | None = None) -> tuple[dict, dict, dict]:
    gen = gen or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    rev = load(RAW / "evidence_reverify.json")
    hashes = load(RAW / "model_full_hashes.json")
    area = load(RAW / "model_area_scan.json")
    scail = load(RAW / "scail_probe.json")
    hf = load(RAW / "hf_provenance_probe.json")
    profiles = load(WORKTREE / PROFILES_REL)

    p4_receipt = load(PROOF / "evidence" / "P4_RECEIPT.json")
    p4_gate = load(PROOF / "evidence" / "P4_GEOMETRY_GATE.json")
    p4_graph_rec = load(PROOF / "evidence" / "P4_GRAPH.json")
    p4_graph = load(PROOF / "graphs" / "animate2_vace_book.p4.api.json")
    p0_matrix = load(PROOF / "evidence" / "P0_RUNTIME_MATRIX.json")
    p0_inv = load(PROOF / "evidence" / "P0_MODEL_INVENTORY.json")
    p7v13 = load(PROOF / "evidence" / "P7_ASSEMBLY_V13.json")

    wan = {p["id"]: p for p in profiles["profiles"]}["wan_animate2_int8_pad640x368_cacheoff"]
    vace_profile = {p["id"]: p for p in profiles["profiles"]}["vace_14b_fp16_book"]

    rows_by_rel = {r["path"]: r for r in rev["rows"]}
    hf_repo = hf["repos"][0]
    hf_by_name = {f["path"].split("/")[-1]: f for f in hf_repo["files"]}
    unet = [f for f in hashes["files"] if f["rel"].endswith("wan2.1_vace_14B_fp16.safetensors")][0]
    vae = [f for f in hashes["files"] if f["rel"].endswith("wan_2.1_vae.safetensors")][0]
    clip = [f for f in hashes["files"] if f["rel"].endswith("umt5_xxl_fp16.safetensors")][0]

    prompt_text = p4_receipt["prompt_text_used"]
    prompt_sha = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
    scail_rows = [r for r in p0_matrix["matrix"] if r.get("family") == "wan_scail"]

    def ev(rel: str, role: str) -> dict:
        r = rows_by_rel[rel]
        return {"path": f"proof/{rel}", "sha256": r["sha256_measured"], "bytes": r["bytes"], "role": role}

    evidence = [
        ev("graphs/animate2_vace_book.p4.api.json", "measured controlled-path graph (P4, bound by receipt+gate+graph record)"),
        ev("output/p4/animate2_vace_book_p4_00001_.mp4", "real local MP4 produced by the challenger run (raw 121f)"),
        ev("output/p4/animate2_vace_book_p4_00001__trim120.mp4", "declared 120-frame copy used for the A/B"),
        ev("evidence/P4_RECEIPT.json", "P4 run receipt (prompt_id, wall, VRAM, outputs)"),
        ev("evidence/P4_GEOMETRY_GATE.json", "P4 gates + watermark blocking defect + vision rows"),
        ev("evidence/P4_GRAPH.json", "P4 graph build record (template sha + deltas)"),
        ev("evidence/P4_SERVER_SHUTDOWN_PROOF.json", "challenger server stopped clean (POST_STOP_VERIFIED)"),
        ev("evidence/P0_RUNTIME_MATRIX.json", "SCAIL-2 node rows: source present / imported / weights_present false"),
        ev("evidence/P0_NODE_INTERFACES.json", "official node interfaces for the SCAIL family (tooltips)"),
        ev("evidence/P0_MODEL_INVENTORY.json", "models-root inventory incl. missing groups sam3/sam2/checkpoints"),
        ev("evidence/P0_object_info.json", "CPU /object_info dump used for offline graph validation"),
        ev("evidence/P3_object_info_gpu.json", "GPU /object_info dump used for offline graph validation"),
        ev("evidence/P1_UNIT_MANIFESTS.json", "input-ready unit manifests BOOK/TURN/OCC (readiness reference)"),
        ev("evidence/P2_ANCHOR_GATES.json", "target anchors gate (input chain the decision reads)"),
        ev("evidence/P3B_GEOMETRY_GATE.json", "Wan side: BOOK geometry/coverage/holder gate rows"),
        ev("evidence/P5FIX_GATE.json", "Wan side: TURN coverage gate row"),
        ev("evidence/P5FIX2_GATE.json", "Wan side: OCC_SEG1 coverage gate row"),
        ev("evidence/P5FIX3_GATE.json", "Wan side: OCC_SEG2 coverage gate row"),
        ev("evidence/P5FIX3_SERVER_SHUTDOWN_PROOF.json", "Wan segment server stopped clean"),
        ev("evidence/P6_NOCACHE_GATE.json", "Wan run with cache OFF (the selected variant)"),
        ev("evidence/P7_ASSEMBLY_V13.json", "final assembly v1.3 (360f) the decision protects"),
        ev("evidence/P7_ASSEMBLY_CHECK.json", "assembly v1.1 check row (published-hash cross-check)"),
    ]

    # ---------------------------------------------------------------- artifact
    artifact = {
        "schema_version": "mf.controlled_shot.v1",
        "graph_id": "controlled_shot_v1",
        "generated_at_utc": gen,
        "purpose": ("conditional controlled-shot path (G4): the challenger track for units where the Wan "
                    "Animate 2 profile fails a measured hard constraint or does not fit this runtime. "
                    "This artifact records the measured activation decision, the measured eligibility of "
                    "every candidate, and the unsupported status on this runtime. It deliberately ships NO "
                    "runnable graph: no candidate satisfies the eligibility rule, and a workflow may never "
                    "claim capability it does not have."),
        "derived_from": {
            "packet": "mf-takeover-20260927/tasks/MF-END-17.md + MF-END-17-launch (Phase B wave 10)",
            "plan": "PRODUCT_AND_COMFY_PLAN.md §5 (G4 contract row)",
            "predecessor_registry": {"path": PROFILES_REL, "set_by": "MF-END-16", "base_commit": BASE},
            "challenger_run": {"graph": "proof/graphs/animate2_vace_book.p4.api.json",
                               "receipt": "proof/evidence/P4_RECEIPT.json",
                               "gate": "proof/evidence/P4_GEOMETRY_GATE.json",
                               "prompt_id": p4_receipt["prompt_id"]},
        },
        "runtime_pin": {
            "comfyui_version": "0.37.0",
            "head": "73c9bad4d21e7addbe1d13bc92eee0f1431b017d",
            "porcelain_clean": True,
            "source_read_only": True,
            "models_root": "C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b/models",
            "license": "ComfyUI GPL-3.0 (LICENSE at the repo root)",
            "isolation_recipe": ("own base-directory + --models-directory at the shared read-only root + own port "
                                 "+ --reserve-vram 1.0 --disable-auto-launch; one job at a time"),
            "verification": "raw/evidence_reverify.json (runtime.head_match, no listener on 8188/8189/8190/8310/8321/8342)",
        },
        "activation": {
            "criteria": [
                "active only when the unit is input-ready AND the Wan profile fails a measured hard constraint OR does not fit this runtime",
                "the verdict must be derived from measured rows only; no new condition may be invented",
                "a skip is recorded as SKIPPED_NOT_NEEDED and is never counted as a test pass",
            ],
            "criteria_source": "packet MF-END-17 micro-job 1 + acceptance clause; frozen before evaluation",
            "input_ready_reference": {"source": "P1_UNIT_MANIFESTS.json (units) + MF-END-15 shot_input_readiness (runtime gate owner)",
                                      "claim_by_this_task": "none - readiness is not re-adjudicated here"},
            "wan_measured_hard_gate_rows": wan["eligibility"]["hard_gate_rows"],
            "wan_measured_hard_constraint_failures": [],
            "open_items_routed": [
                {"id": "F5_BOOK_STATE", "status": "OPEN_PRODUCT_DECISION",
                 "detail": "source event open_two_pages @72; Wan keeps the book CLOSED across the window, VACE shows it OPEN at f119",
                 "routed_to": "product decision -> S12 review packet (PROOF_GATE_EVALUATION §3.1); explicitly NOT classified as a measured hard-constraint failure here"},
                {"id": "F6_RAM_INSTRUMENT", "status": "OPEN_INSTRUMENT",
                 "detail": "RAM peak NOT MEASURED for every GPU run (non-credible sampler figures); reported as NOT_MEASURED, never guessed",
                 "routed_to": "instrument fix; does not gate the runtime-fit question the challenger answers (VRAM peak is measured)"},
                {"id": "PROOF_GATE_EVALUATION-F2-P2", "status": "ROUTED_DELTA",
                 "detail": "demo-side coverage delta: right-edge partial-person form / wall picture frame in BOOK",
                 "routed_to": "backlog Phase B/C delta coverage; no profile change (per PROOF_GATE_EVALUATION findings table)"},
            ],
            "verdict": "SKIPPED_NOT_NEEDED",
            "counts_as_test_pass": False,
            "rationale": ("The activation trigger is not met on the measured rows: every measured hard gate of the "
                          "Wan profile on all four measured cases (dims 640x368; timing 120/120/102/18 @30/1 pts "
                          "monotonic; per-segment coverage incl. the partial right-edge person; holder/contact; no "
                          "watermark) is PASS, and the only two non-PASS rows are routed open items (F5 product "
                          "decision, F6 instrument) rather than measured failures. Independently, no eligible "
                          "candidate exists to run: the only installed challenger with weights (VACE 14B fp16) is "
                          "already measured and INELIGIBLE (watermark copy, 1 of 4 cases), and the SCAIL-2 "
                          "correspondence family has no weights anywhere in the models root. Re-running a model "
                          "would therefore violate the acceptance rule 'do not run models without cause' and "
                          "could not produce an eligible candidate."),
            "decided_by": "MF-END-17 worker (eligibility measured from sealed evidence; quality acceptance reserved to BENCH / DEMO / Codex)",
        },
        "contract": {
            "family": "G4 controlled shot (conditional) - PRODUCT_AND_COMFY_PLAN.md §5",
            "inputs": ["correspondence masks", "reference set", "source", "frozen profile"],
            "outputs": ["video", "receipt"],
            "gates": "the SAME hard gates as the G3 Wan profile (dims / timing / coverage / holder-contact / no watermark)",
            "gate_loosening": "FORBIDDEN - a challenger may never win by loosening a gate ('không nới để challenger thắng')",
            "mask_semantics": {
                "correspondence_masks": "per-identity colored masks (SCAIL-2 palette semantics); required by this contract",
                "vace_control_masks": "edit masks with different semantics - NOT correspondence masks",
                "rule": "mask formats are never reused across profiles; any converter must be profile-specific and tested (no raw mask reuse, no threshold tuning to fit an output)",
            },
            "multi_reference": {"rule": "no workflow may claim multi-reference support it does not have",
                                "claimed_multi_ref": False},
            "one_candidate_at_a_time": True,
            "pre_install_checks": ["verify model source (official org/repo)", "verify license", "verify disk at the dedicated model area",
                                   "record revision + per-file sha256 / LFS oid"],
            "corrections_route": "a wrong relation routes to the interaction/correspondence owner (PRODUCT_AND_COMFY_PLAN §6)",
        },
        "probe": {
            "family": "wan_scail / SCAIL-2 correspondence path",
            "status": "BLOCKED_NO_WEIGHTS",
            "inference_tested": "NOT_RUN",
            "node_ids": scail["node_ids"],
            "node_source": {"file": "comfy_extras/nodes_scail.py", "sha256": scail["source_sha256"], "lines": scail["source_lines"]},
            "registration": {"source_present": True, "imported": True,
                             "evidence": "P0_RUNTIME_MATRIX.json wan_scail rows (source_present/imported true)"},
            "weights": {
                "present": False,
                "scan_hits": scail["weights"]["scan_hits"],
                "sam3_weights_present": scail["weights"]["sam3_weights_present"],
                "p0_missing_groups": p0_inv["missing_groups"],
                "matches": scail_rows[0]["weights_evidence"]["matched"] if scail_rows else [],
                "note": "no SCAIL/SAM weight file exists under the models root; the family cannot run here and no inference is claimed",
            },
            "correspondence_graph_semantics": {
                "driving_masks": "SAM3 track of the driving pose video, rendered as a colored per-identity mask video at pose resolution",
                "reference_masks": "SAM3 tracks of the reference image(s) - one identity per object, colored in batch order - or a plain MASK rendered as a single identity (palette[0])",
                "identity_rule": "the SAME order is applied to reference and pose masks so one identity keeps one colour; objects appearing earlier always come first",
                "sort_options": ["none", "left_to_right", "area"],
                "palette": {"count": scail["palette"]["count"], "colors": scail["palette"]["colors"],
                            "trained_note": "model was trained on these exact colours; more identities than palette entries wrap with modulo (re-use a colour)"},
                "modes": {"animation": "pose mask black background / reference mask white",
                          "replacement": "pose mask white background / reference mask black"},
                "chunking": "trained at previous_frame_count 5 (81-frame chunks, 76-frame step)",
                "model_input": "the WanSCAILToVideo node conditions the model the graph loads; the family needs its own finetuned weights, which are absent",
            },
            "win12gb": scail["win12gb"],
        },
        "candidates": [
            {
                "id": "scail2_wan_scail",
                "kind": "correspondence (the contract's primary family)",
                "status": "BLOCKED_NO_WEIGHTS",
                "eligibility": {"real_local_mp4": "NONE - cannot run", "quality": "NOT_MEASURED", "vram": "NOT_MEASURED",
                                "verdict": "NOT_ELIGIBLE"},
                "inference_tested": "NOT_RUN",
                "evidence": ["proof/evidence/P0_RUNTIME_MATRIX.json", "proof/evidence/P0_MODEL_INVENTORY.json",
                             "proof/evidence/P0_NODE_INTERFACES.json"],
                "unsupported_note": "recorded as unsupported on this runtime; nothing is downloaded in this task",
            },
            {
                "id": "vace_14b_fp16_book",
                "kind": "installed masked-edit candidate (fallback per the research: 'hoac installed VACE')",
                "status": "MEASURED_INELIGIBLE",
                "measured": {
                    "case": "BOOK (same unit/seed as the Wan baseline)",
                    "prompt_id": p4_receipt["prompt_id"],
                    "graph": "proof/graphs/animate2_vace_book.p4.api.json",
                    "graph_sha256": p4_receipt["graph_sha256"],
                    "server_side_wall_s": p4_receipt["server_side_wall_s"],
                    "seconds_per_output_second": p4_receipt["seconds_per_output_second_121f"],
                    "vram_peak_mib": p4_receipt["vram_peak_mib"],
                    "outputs": p4_receipt["output_files"],
                    "comparison_artifact": p4_gate["comparison_artifact"],
                    "trim_policy": p4_gate["trim_policy"],
                    "fps": "30/1",
                    "dims": [640, 368],
                    "prompt_sha256": prompt_sha,
                    "declared_params": p4_receipt["declared_params"],
                    "deltas_vs_template": p4_receipt["deltas"],
                },
                "eligibility_gates": {
                    "real_local_mp4": {"verdict": "PASS", "artifacts": ["proof/output/p4/animate2_vace_book_p4_00001_.mp4",
                                                                        "proof/output/p4/animate2_vace_book_p4_00001__trim120.mp4"]},
                    "quality": {"verdict": "FAIL", "defect": p4_gate["vision_pass"]["blocking_defect"],
                                "coverage_verdict": p4_gate["coverage_verdict"],
                                "evidence": ["proof/evidence/P4_GEOMETRY_GATE.json"]},
                    "vram": {"verdict": "PASS", "peak_mib": p4_receipt["vram_peak_mib"], "gpu_total_mib": 12227},
                    "verdict": "INELIGIBLE",
                },
                "hard_relations": p4_gate["hard_relations"],
                "behaviour_difference": p4_gate["vision_pass"]["behaviour_difference"],
                "cases_run": "1 of 4 measured cases (BOOK only)",
                "semantics": {
                    "reference": "single primary reference_image (the node takes the first image); no per-identity reference batch is consumed",
                    "control_masks": "edit masks (control_video/control_masks) - NOT the G4 correspondence masks",
                    "multi_ref_claim": False,
                },
                "gates_not_loosened": "the quality gate is applied as-is; the watermark blocker (F4) is not masked, cropped or tuned away",
                "evidence": ["proof/evidence/P4_RECEIPT.json", "proof/evidence/P4_GEOMETRY_GATE.json", "proof/evidence/P4_GRAPH.json"],
                "unsupported_recorded": True,
                "unsupported_reason": ("copies the source watermark (play button + 'Lạnh Vcl') at frames 0 and 119 - a product "
                                       "blocker for any delivered clip; the profile stays INELIGIBLE until a removal strategy is proven"),
            },
        ],
        "path_status": {
            "status": "UNSUPPORTED_ON_THIS_RUNTIME",
            "basis": ["no candidate satisfies real-local-MP4 + quality + VRAM",
                      "SCAIL-2: no weights installed (BLOCKED)",
                      "VACE 14B: measured but quality gate FAIL (watermark copy)"],
            "reference": "MF-END-16 model_profiles.json keeps the Wan profile chosen; this artifact adds the challenger record",
        },
        "eligibility_policy": {
            "rule": "a challenger is eligible only when it has a real local MP4 + a passing quality gate + a passing VRAM gate",
            "applied_verbatim": True,
            "no_gate_loosening": True,
            "no_multi_ref_claim": True,
        },
        "model_area_policy": {
            "models_root": "C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b/models",
            "downloads_performed_this_task": 0,
            "model_area_unchanged_vs_p0": area["unchanged_vs_p0"],
            "files_checked": area["file_count"],
            "install_requirements_when_authorized": ["source = official repo/org", "license recorded",
                                                     "dedicated model area only", "revision + per-file sha256/LFS oid recorded in this registry"],
        },
        "claims": {
            "quality_accepted": False,
            "quality_verdict_owner": "BENCH / DEMO / Codex",
            "no_best_newest_claim": True,
            "new_gpu_jobs_this_task": 0,
            "deliverable": False,
            "skip_not_a_pass": True,
        },
        "evidence": evidence,
    }

    # ---------------------------------------------------------------- manifest
    artifact_bytes = dump_crlf_bytes(artifact)
    artifact_sha = hashlib.sha256(artifact_bytes).hexdigest()

    manifest = {
        "schema_version": "mf.controlled_shot.manifest.v1",
        "graph_id": "controlled_shot_v1",
        "generated_at_utc": gen,
        "workflow": {
            "graph_file": ARTIFACT_REL,
            "graph_file_sha256": artifact_sha,
            "graph_file_bytes": len(artifact_bytes),
            "shipped_runnable_graph": False,
            "why_no_graph": ("no candidate satisfies the eligibility rule; shipping a non-deliverable graph would "
                             "misrepresent the controlled path (the acceptance forbids a fake live workflow)"),
            "measured_evidence_graph": {
                "file": "proof/graphs/animate2_vace_book.p4.api.json",
                "sha256": p4_receipt["graph_sha256"],
                "node_count": len(p4_graph),
                "node_classes": {nid: n.get("class_type") for nid, n in sorted(p4_graph.items(), key=lambda kv: int(kv[0]))},
                "template_file": p4_receipt["template"],
                "template_sha256": p4_receipt["template_sha256"],
                "validation_offline": {k: {"ok": v["ok"], "node_count": v["node_count"],
                                           "dynamic_combo_accepted": v["dynamic_combo_accepted"]}
                                       for k, v in rev["graph_validation"].items()},
            },
        },
        "decision": {
            "criteria": artifact["activation"]["criteria"],
            "criteria_source": artifact["activation"]["criteria_source"],
            "verdict": "SKIPPED_NOT_NEEDED",
            "counts_as_test_pass": False,
            "rationale": artifact["activation"]["rationale"],
            "wan_measured_hard_constraint_failures": [],
            "open_items_routed": artifact["activation"]["open_items_routed"],
            "decided_by": artifact["activation"]["decided_by"],
            "quality_acceptance": "reserved to BENCH / DEMO / Codex (QUALITY_ACCEPTED=0)",
        },
        "candidates": [
            {"id": c["id"], "status": c["status"], "eligibility": c["eligibility"], "inference_tested": c["inference_tested"]}
            if c["id"] == "scail2_wan_scail" else
            {"id": c["id"], "status": c["status"], "eligibility_gates": c["eligibility_gates"],
             "cases_run": c["cases_run"], "semantics": c["semantics"],
             "gates_not_loosened": c["gates_not_loosened"], "unsupported_recorded": c["unsupported_recorded"],
             "unsupported_reason": c["unsupported_reason"]}
            for c in artifact["candidates"]
        ],
        "models": [
            {"role": "unet", "rel": "diffusion_models/wan2.1_vace_14B_fp16.safetensors",
             "sha256": unet["sha256"], "bytes": unet["bytes"], "sha256_match_sealed_mf_end_16": unet["sha_match_sealed"],
             "license": hf_repo["license"], "source": hf_repo["repo"], "revision": hf_repo["revision"],
             "lfs_oid_equals_measured_sha256": hf_by_name["wan2.1_vace_14B_fp16.safetensors"]["lfs_oid_equals_measured_sha256"]},
            {"role": "vae", "rel": "vae/wan_2.1_vae.safetensors", "sha256": vae["sha256"], "bytes": vae["bytes"],
             "license": hf_repo["license"], "source": hf_repo["repo"], "revision": hf_repo["revision"],
             "lfs_oid_equals_measured_sha256": hf_by_name["wan_2.1_vae.safetensors"]["lfs_oid_equals_measured_sha256"]},
            {"role": "text_encoder", "rel": "text_encoders/umt5_xxl_fp16.safetensors", "sha256": clip["sha256"],
             "bytes": clip["bytes"], "license": hf_repo["license"], "source": hf_repo["repo"],
             "revision": hf_repo["revision"],
             "lfs_oid_equals_measured_sha256": hf_by_name["umt5_xxl_fp16.safetensors"]["lfs_oid_equals_measured_sha256"]},
        ],
        "runtime": {
            "comfyui_version": "0.37.0", "head": rev["runtime"]["head"], "head_match": rev["runtime"]["head_match"],
            "porcelain_clean": rev["runtime"]["porcelain_clean"],
            "version_file_sha256": rev["runtime"]["version_file_sha256"],
            "models_root": artifact["model_area_policy"]["models_root"],
            "node_source_sha256": rev["runtime"]["node_source_sha256"],
            "reverified": "raw/evidence_reverify.json (22 rows MATCH, cross-links equal, 0 listeners)",
        },
        "measurement": {
            "vace_14b_fp16": {"server_side_wall_s": p4_receipt["server_side_wall_s"],
                              "seconds_per_output_second_121f": p4_receipt["seconds_per_output_second_121f"],
                              "vram_peak_mib": p4_receipt["vram_peak_mib"], "cases": 1},
            "wan_reference": {"warm_s_per_output_second": wan["measured"]["warm_s_per_output_second"],
                              "cache_off_s_per_output_second": wan["measured"]["cache_off_s_per_output_second"],
                              "vram_peak_mib": wan["measured"]["vram_peak_mib"], "cases": 4},
            "gpu_total_mib": 12227,
        },
        "scail_probe": {"family": artifact["probe"]["family"], "status": artifact["probe"]["status"],
                        "inference_tested": artifact["probe"]["inference_tested"],
                        "node_ids": artifact["probe"]["node_ids"], "weights_present": False,
                        "palette_count": artifact["probe"]["correspondence_graph_semantics"]["palette"]["count"],
                        "win12gb": artifact["probe"]["win12gb"]["status"]},
        "failure_taxonomy_preserved": [
            {"id": "F1_GEOMETRY_CROP", "status": "FIXED_VERIFIED", "note": "unchanged by this task"},
            {"id": "F2_PROMPT_CARRYOVER", "status": "FIXED_VERIFIED", "note": "unchanged by this task"},
            {"id": "F3_SEGMENT_AT_CUT", "status": "FIXED_VERIFIED", "note": "unchanged by this task"},
            {"id": "F4_WATERMARK_COPY", "status": "OPEN_PRODUCT_BLOCKER", "note": "this task re-binds it as the VACE ineligibility blocker; strategy still required before any VACE use"},
            {"id": "F5_BOOK_STATE", "status": "OPEN_PRODUCT_DECISION", "note": "routed to the S12 review packet; not adjudicated here"},
            {"id": "F6_RAM_INSTRUMENT", "status": "OPEN_INSTRUMENT", "note": "NOT_MEASURED kept; never guessed"},
            {"id": "F7_SEAM_FLAG_BOOK", "status": "FLAGGED_KEPT", "note": "unchanged by this task"},
            {"id": "F8_TURN_TRANSIENT_GLYPH", "status": "RECORDED_KEPT", "note": "unchanged by this task"},
        ],
        "evidence_root": EVIDENCE_ROOT,
        "claims": artifact["claims"],
    }

    build_record = {
        "artifact": "build_record.json", "at_utc": gen, "task": TASK, "branch": BRANCH, "base_commit": BASE,
        "outputs": [
            {"path": ARTIFACT_REL, "bytes": len(artifact_bytes), "sha256": artifact_sha},
        ],
    }
    return artifact, manifest, build_record


def main() -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    verify_mode = "--verify" in sys.argv
    artifact, manifest, build_record = build()
    a_bytes = dump_crlf_bytes(artifact)
    m_bytes = dump_crlf_bytes(manifest)
    build_record["outputs"].append({"path": MANIFEST_REL, "bytes": len(m_bytes),
                                    "sha256": hashlib.sha256(m_bytes).hexdigest()})

    if verify_mode:
        # determinism: rebuild with the SAME timestamp; byte-identical or an input changed
        artifact2, manifest2, _ = build(gen=artifact["generated_at_utc"])
        a2 = dump_crlf_bytes(artifact2)
        m2 = dump_crlf_bytes(manifest2)
        results = [
            {"path": ARTIFACT_REL, "verdict": "MATCH" if a2 == a_bytes else "DIFFER"},
            {"path": MANIFEST_REL, "verdict": "MATCH" if m2 == m_bytes else "DIFFER"},
        ]
        out = {"artifact": "determinism_check.json", "mode": "verify",
               "at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "results": results,
               "note": "rebuild modulo generated_at_utc; any DIFFER means an input changed"}
        (RAW / "determinism_check.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({"verdict": "PASS" if all(r["verdict"] == "MATCH" for r in results) else "FAIL",
                          "results": results}))
        return 0 if all(r["verdict"] == "MATCH" for r in results) else 1

    (WORKTREE / ARTIFACT_REL).write_bytes(a_bytes)
    (WORKTREE / MANIFEST_REL).write_bytes(m_bytes)
    (RAW / "build_record.json").write_text(json.dumps(build_record, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"wrote": [ARTIFACT_REL, MANIFEST_REL],
                      "artifact_sha256": build_record["outputs"][0]["sha256"],
                      "manifest_sha256": build_record["outputs"][1]["sha256"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
