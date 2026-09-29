"""MF-END-16 tool — build the three write-set JSON deliverables from the frozen proof evidence.

Inputs (read-only): the Phase-A proof root (graphs/evidence), this run's raw/model_full_hashes.json
and raw/evidence_reverify.json.  Outputs (whole-file generation, all NEW files):
  app/media_workflows/wan_shot_v1.json
  app/media_workflows/wan_shot_v1.manifest.json
  app/media_workflows/model_profiles.json

Deterministic: same inputs -> same bytes.  Anything not measured is labelled as such;
nothing is invented (notably: accepted_seconds = 0 -> cost per accepted second UNDEFINED).
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import time
from pathlib import Path

PROOF = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/proof")
RUN_ROOT = Path(__file__).resolve().parent.parent
RAW = RUN_ROOT / "raw"
WORKTREE = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-16")
OUT_DIR = WORKTREE / "app" / "media_workflows"

TEMPLATE_PATH = (
    "C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/"
    "mf-reskin-correction-20260922/20260922T0955Z/VIDEO14B/waveB/workflows/mf_animate2_book4s.shim.api.json"
)
TEMPLATE_SHA = "6e92d82b20cb2d9b1e6a9fe0e8d9cddc88ea81fdf4151ef4c6b62e21cf158fa5"

RUNTIME = {
    "comfyui_dir": "C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b/ComfyUI",
    "version": "0.37.0",
    "head": "73c9bad4d21e7addbe1d13bc92eee0f1431b017d",
    "models_root": "C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b/models",
    "license": "ComfyUI GPL-3.0 (LICENSE at the repo root)",
}

HF = {
    "wan_repo": "Comfy-Org/Wan-Animate-2",
    "wan_rev": "ed158470869ff31fa51cf56012dac33fb00f494b",
    "vace_repo": "Comfy-Org/Wan_2.1_ComfyUI_repackaged",
    "vace_rev": "617a7633e636506f850e043bc4605f290a466a8e",
}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024 * 4), b""):
            h.update(chunk)
    return h.hexdigest()


def write_crlf_json(path: Path, obj) -> tuple[int, str]:
    text = json.dumps(obj, indent=1, ensure_ascii=False)
    data = text.replace("\n", "\r\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return len(data), sha256_bytes(data)


def reverify_map() -> dict:
    d = load_json(RAW / "evidence_reverify.json")
    return {r["path"]: r for r in d["rows"]}


def model_map() -> dict:
    d = load_json(RAW / "model_full_hashes.json")
    return {(f["group"], f["file"]): f for f in d["files"]}


def main() -> int:
    verify_only = "--verify" in sys.argv
    rv = reverify_map()
    mm = model_map()

    OUT_GRAPH = OUT_DIR / "wan_shot_v1.json"
    OUT_MANIFEST = OUT_DIR / "wan_shot_v1.manifest.json"
    OUT_PROFILES = OUT_DIR / "model_profiles.json"

    def stamp_for(path: Path) -> str:
        """Determinism: in --verify mode reuse the on-disk timestamp so a rebuild must be
        byte-identical modulo (nothing but) the build timestamp."""
        if verify_only and path.is_file():
            return load_json(path).get("generated_at_utc") or "MISSING"
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    p3b_graph = load_json(PROOF / "graphs" / "animate2_book.p3b.api.json")
    p6_graph = load_json(PROOF / "graphs" / "animate2_book.p6nocache.api.json")
    turn_graph = load_json(PROOF / "graphs" / "animate2_turn.p5fix.api.json")
    seg1_graph = load_json(PROOF / "graphs" / "animate2_occ_seg1.p5fix2.api.json")
    seg2_graph = load_json(PROOF / "graphs" / "animate2_occ_seg2.p5fix3.api.json")

    # ---- graph section: the cache-off variant, byte-identical modulo the output prefix knob ----
    graph = copy.deepcopy(p6_graph)
    PREFIX = "wan_shot_v1/book"
    graph["246"]["inputs"]["filename_prefix"] = PREFIX
    graph["292"]["inputs"]["filename_prefix"] = PREFIX
    differing = [
        k for k in p6_graph
        if json.dumps(p6_graph[k], sort_keys=True) != json.dumps(graph[k], sort_keys=True)
    ]
    assert sorted(differing) == ["246", "292"], f"unexpected deltas vs run graph: {differing}"
    assert "672:594" not in graph, "cache node must not exist in the pinned cache-off variant"

    graph_object_sha = sha256_bytes(
        json.dumps(graph, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )

    # ---- prompts (frozen verbatim; sha256 over the exact text) ----
    def prompt_row(g, node="672:582"):
        text = g[node]["inputs"]["text"]
        return {"node": node, "sha256": sha256_bytes(text.encode("utf-8")), "chars": len(text), "text": text}

    prompts = {
        "BOOK": prompt_row(p3b_graph),
        "TURN": prompt_row(turn_graph),
        "OCC_SEG1": prompt_row(seg1_graph),
        "OCC_SEG2": prompt_row(seg2_graph),
    }

    # ---- model table (full sha256 measured 2026-09-28; HF LFS oid == measured sha) ----
    REV_DATES = {"wan": "2026-08-17T05:28:11Z", "vace": "2026-08-17T06:09:26Z"}  # HF API revision lastModified, probed 2026-09-28

    def model_row(group, file, role, why, repo_key="wan"):
        f = mm[(group, file)]
        return {
            "role": role,
            "file": file,
            "rel": f"{group}/{file}",
            "path": f["path"],
            "bytes": f["bytes"],
            "sha256": f["sha256"],
            "sha256_first_1mib": f["sha256_first_1mib"],
            "license": "apache-2.0",
            "source": {"repo": HF[repo_key + "_repo"], "revision": HF[repo_key + "_rev"],
                       "revision_last_modified_utc": REV_DATES[repo_key],
                       "hf_lfs_oid_equals_measured_sha256": True,
                       "probe": "HF API /api/models/<repo>/revision/<rev> (license + date) and /tree (LFS oid) compared to the locally measured full sha256, 2026-09-28"},
            "why_used": why,
        }

    models_wan = [
        model_row("diffusion_models", "wan_animate_2_int8_convrot.safetensors", "unet",
                  "the pinned checkpoint variant: Wan Animate 2 INT8 convrot (not bf16/fp16)"),
        model_row("loras", "lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors", "lora",
                  "the 6-step lcm distill LoRA the official graph chains"),
        model_row("text_encoders", "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "text_encoder",
                  "text encoder pinned by the graph (CLIPLoader type=wan)"),
        model_row("clip_vision", "clip_vision_h.safetensors", "clip_vision",
                  "CLIP vision for reference + drive-frame conditioning"),
        model_row("vae", "Wan2_1_VAE_bf16.safetensors", "vae", "the graph's decode/encode VAE"),
    ]
    model_vace = model_row("diffusion_models", "wan2.1_vace_14B_fp16.safetensors", "unet",
                           "challenger profile checkpoint (VACE 14B fp16)", "vace")

    # ---- case table (everything bound to a verified file) ----
    def probe(row):
        return row.get("probe", row.get("ffprobe"))

    cases = [
        {
            "case_id": "BOOK",
            "unit_id": "BOOK-UNIT-001",
            "source": {
                "file": "BOOK_src.mp4", "rel": "inputs/BOOK_src.mp4",
                "sha256": rv["inputs/BOOK_src.mp4"]["sha256_measured"],
                "dims": [640, 360], "frames": 120, "fps": "30/1", "duration": "4.000000",
                "span": [0, 120],
            },
            "anchor": {
                "file": "anchor_book_p2_00001_.png", "rel": "inputs/anchor_book_p2_00001_.png",
                "sha256": rv["inputs/anchor_book_p2_00001_.png"]["sha256_measured"],
                "dims": [640, 368], "mode": "RGB",
            },
            "prompt_sha256": prompts["BOOK"]["sha256"],
            "seed": 582699151003550,
            "graph_evidence": {"file": "graphs/animate2_book.p3b.api.json", "sha256": rv["graphs/animate2_book.p3b.api.json"]["sha256_measured"]},
            "receipt": {"file": "evidence/P3B_RECEIPT.json", "prompt_id": "d1f4e097-458d-4bd4-8049-fe6da26f91c1",
                        "graph": "graphs/animate2_book.p3b.api.json", "cache": "on",
                        "server_side_wall_s": 154.67, "seconds_per_output_second": 38.67, "vram_peak_mib": 10973},
            "output_main": {
                "file": "output/p3b/animate2_book_p3b_00001_.mp4", "bytes": 208053,
                "sha256": rv["output/p3b/animate2_book_p3b_00001_.mp4"]["sha256_measured"],
                "ffprobe": {"width": 640, "height": 368, "r_frame_rate": "30/1", "duration": "4.000000", "nb_read_frames": "120"},
            },
            "gate": {"file": "evidence/P3B_GEOMETRY_GATE.json", "coverage": "PASS", "seam": "NO_VISIBLE_SEAM_DEFECT (numeric flag kept)"},
            "pinned_variant_run": {
                "note": "the same case re-run with the pinned cache-OFF wiring (pixel-identical)",
                "file": "output/p6_book_nocache/animate2_book_nocache_00001_.mp4",
                "sha256": rv["output/p6_book_nocache/animate2_book_nocache_00001_.mp4"]["sha256_measured"],
                "graph": "graphs/animate2_book.p6nocache.api.json",
                "graph_sha256": rv["graphs/animate2_book.p6nocache.api.json"]["sha256_measured"],
                "prompt_id": "06302bb4-68d1-4a48-be56-59c14451e100",
                "server_side_wall_s": 135.21, "seconds_per_output_second": 33.8, "vram_peak_mib": 10763,
            },
        },
        {
            "case_id": "TURN",
            "unit_id": "TURN-UNIT-001",
            "source": {
                "file": "TURN_795_src.mp4", "rel": "inputs/TURN_795_src.mp4",
                "sha256": rv["inputs/TURN_795_src.mp4"]["sha256_measured"],
                "dims": [640, 360], "frames": 120, "fps": "30/1", "duration": "4.000000",
                "span": [0, 120],
            },
            "anchor": {
                "file": "anchor_turn_p2_00001_.png", "rel": "inputs/anchor_turn_p2_00001_.png",
                "sha256": rv["inputs/anchor_turn_p2_00001_.png"]["sha256_measured"],
                "dims": [640, 368],
            },
            "prompt_sha256": prompts["TURN"]["sha256"],
            "seed": 2026092811,
            "graph_evidence": {"file": "graphs/animate2_turn.p5fix.api.json", "sha256": rv["graphs/animate2_turn.p5fix.api.json"]["sha256_measured"]},
            "receipt": {"file": "evidence/P5FIX_TURN_RECEIPT.json", "prompt_id": "4d4eda1b-d590-4073-aaf0-5e43daf2b36b",
                        "graph": "graphs/animate2_turn.p5fix.api.json", "cache": "off",
                        "server_side_wall_s": 134.94, "seconds_per_output_second": 33.73, "vram_peak_mib": 10855},
            "output_main": {
                "file": "output/p5fix_turn/animate2_turn_p5fix_00001_.mp4", "bytes": 409148,
                "sha256": rv["output/p5fix_turn/animate2_turn_p5fix_00001_.mp4"]["sha256_measured"],
                "ffprobe": {"width": 640, "height": 368, "r_frame_rate": "30/1", "duration": "4.000000", "nb_read_frames": "120"},
            },
            "gate": {"file": "evidence/P5FIX_GATE.json", "coverage": "PASS", "note": "transient doubled glyph at f60 recorded"},
        },
        {
            "case_id": "OCC_SEG1",
            "unit_id": "OCC-UNIT-001",
            "source": {
                "file": "p5fix2_occ_seg1.mp4", "rel": "inputs/p5fix2_occ_seg1.mp4",
                "sha256": rv["inputs/p5fix2_occ_seg1.mp4"]["sha256_measured"],
                "dims": [640, 360], "frames": 102, "fps": "30/1", "duration": "3.400000",
                "span": [0, 102], "split_from": "OCC window cut at frame 102",
            },
            "anchor": {
                "file": "anchor_occ_p2_00001_.png", "rel": "inputs/anchor_occ_p2_00001_.png",
                "sha256": rv["inputs/anchor_occ_p2_00001_.png"]["sha256_measured"], "dims": [640, 368],
            },
            "prompt_sha256": prompts["OCC_SEG1"]["sha256"],
            "seed": 2026092831,
            "graph_evidence": {"file": "graphs/animate2_occ_seg1.p5fix2.api.json", "sha256": rv["graphs/animate2_occ_seg1.p5fix2.api.json"]["sha256_measured"]},
            "receipt": {"file": "evidence/P5FIX2_SEG1_RECEIPT.json", "prompt_id": "4314671a-3311-4f0b-9ae6-597b9202d871",
                        "graph": "graphs/animate2_occ_seg1.p5fix2.api.json", "cache": "off",
                        "server_side_wall_s": 120.55, "seconds_per_output_second": 30.14, "vram_peak_mib": 10875},
            "output_main": {
                "file": "output/p5fix2_occ_seg1/animate2_occ_seg1_p5fix2_00001_.mp4", "bytes": 149258,
                "sha256": rv["output/p5fix2_occ_seg1/animate2_occ_seg1_p5fix2_00001_.mp4"]["sha256_measured"],
                "ffprobe": {"width": 640, "height": 368, "r_frame_rate": "30/1", "duration": "3.400000", "nb_read_frames": "102"},
            },
            "gate": {"file": "evidence/P5FIX2_GATE.json", "coverage": "PASS",
                     "comparator_note": "the recorded dims_640x368 boolean in that gate file is a false negative "
                                        "(int vs str comparison); measured dims were 640x368 — documented in P5FIX3_GATE.gates_note"},
        },
        {
            "case_id": "OCC_SEG2",
            "unit_id": "OCC-UNIT-001",
            "source": {
                "file": "p5fix2_occ_seg2.mp4", "rel": "inputs/p5fix2_occ_seg2.mp4",
                "sha256": rv["inputs/p5fix2_occ_seg2.mp4"]["sha256_measured"],
                "dims": [640, 360], "frames": 18, "fps": "30/1", "duration": "0.600000",
                "span": [102, 120], "split_from": "OCC window cut at frame 102",
            },
            "anchor": {
                "file": "anchor_occ_seg2_p5fix2_00001_.png", "rel": "inputs/anchor_occ_seg2_p5fix2_00001_.png",
                "sha256": rv["inputs/anchor_occ_seg2_p5fix2_00001_.png"]["sha256_measured"], "dims": [640, 368],
            },
            "prompt_sha256": prompts["OCC_SEG2"]["sha256"],
            "seed": 2026092841,
            "graph_evidence": {"file": "graphs/animate2_occ_seg2.p5fix3.api.json", "sha256": rv["graphs/animate2_occ_seg2.p5fix3.api.json"]["sha256_measured"]},
            "receipt": {"file": "evidence/P5FIX3_SEG2_RECEIPT.json", "prompt_id": "45eecffd-a744-46f3-bafd-4bcdadc45ddd",
                        "graph": "graphs/animate2_occ_seg2.p5fix3.api.json", "cache": "off",
                        "server_side_wall_s": 31.21, "seconds_per_output_second": 7.8, "vram_peak_mib": 10931},
            "output_main": {
                "file": "output/p5fix3_occ_seg2/animate2_occ_seg2_p5fix3_00001_.mp4", "bytes": 46422,
                "sha256": rv["output/p5fix3_occ_seg2/animate2_occ_seg2_p5fix3_00001_.mp4"]["sha256_measured"],
                "ffprobe": {"width": 640, "height": 368, "r_frame_rate": "30/1", "duration": "0.600000", "nb_read_frames": "18"},
            },
            "gate": {"file": "evidence/P5FIX3_GATE.json", "coverage": "PASS",
                     "deviations": "generated book OPEN vs source closed; hooded jacket reads more detailed (recorded, not hidden)"},
        },
    ]

    # ---- frame mapping (measured plan; the assembly graph is the executable proof) ----
    frame_mapping = {
        "timebase": {"fps": "30/1", "source_dims_wh": [640, 360], "output_dims_wh": [640, 368],
                     "pad": "ResizeAndPadImage (P3B_PAD) target 640x368, black, interpolation=area, CENTERED => 4 rows top + 4 rows bottom",
                     "source_node": "comfy_extras/nodes_images.py:594-641 (scale=min(fit), centered pad)"},
        "segments": [
            {"unit": "BOOK", "source_span": [0, 120], "output_span": [0, 120], "map": "identity i -> i", "frames": 120},
            {"unit": "TURN", "source_span": [0, 120], "output_span": [0, 120], "map": "identity i -> i", "frames": 120},
            {"unit": "OCC_SEG1", "source_span": [0, 102], "output_span": [0, 102], "map": "identity i -> i", "frames": 102},
            {"unit": "OCC_SEG2", "source_span": [102, 120], "output_span": [0, 18], "map": "i -> i - 102", "frames": 18},
        ],
        "cut_map": {"BOOK": {"cuts": [], "evidence": "P5FIX2_CUT_SCAN windows.BOOK verdict NO_CUT_OVER_THRESHOLD"},
                    "TURN": {"cuts": [], "evidence": "P5FIX2_CUT_SCAN windows.TURN"},
                    "OCC": {"cut_frames": [102], "rule": "changed_fraction>=0.50 AND mean_abs_diff>=12.0 (declared threshold; measured 102.10 vs median 0.004)",
                            "evidence": "P5FIX2_CUT_SCAN + P5FIX2_SPLIT"}},
        "assembly": {
            "graph": "graphs/p7_assembly_v13.api.json",
            "graph_sha256": rv["graphs/p7_assembly_v13.api.json"]["sha256_measured"],
            "prompt_id": "e79a9cb7-9138-4117-90d3-b6c1defd3570",
            "order": ["BOOK", "TURN", "OCC_SEG1", "OCC_SEG2"],
            "total_frames": 360, "duration_s": "12.000000",
            "audio": "graph-native LoadAudio x3 (BOOK_src.mp4 + TURN_795_src.mp4 + OCC_14768_src.mp4) + AudioConcat -> ConcatenateVideo.complete_audio; the two OCC segments share the one OCC window audio",
            "staged_copies_byte_identical": True,
            "output": {"file": "output/p7/assembly_v13_00001_.mp4", "bytes": 819282,
                       "sha256": rv["output/p7/assembly_v13_00001_.mp4"]["sha256_measured"],
                       "ffprobe": {"width": 640, "height": 368, "r_frame_rate": "30/1", "duration": "12.000000", "nb_read_frames": "360"},
                       "audio_ffprobe": {"codec": "aac", "sample_rate": "44100", "channels": 2, "duration": "11.980998"}},
            "superseded_kept_on_disk": ["output/p7/assembly_v12_00001_.mp4", "output/p7/assembly_v11_00001_.mp4", "output/p7/assembly_v1_00001_.mp4"],
            "note": "assembly output stays 640x368 (it does NOT crop the 4+4 pad rows): the pad is a conditioning geometry, the output keeps it — declared, measured",
        },
        "chunk_semantics": {
            "node_shape": "4n+1 (measured: VACE raw clip 121 frames for a 120-frame request; Wan output trimmed to 120 by TrimVideoLatent 672:602 + ImageFromBatch 672:604)",
            "context_length": 21, "context_overlap": 8,
            "overlap_inert_measured": "8 -> 16 produced a pixel-identical clip (max_abs 0 over 120 frames); overlap is not a quality lever here",
            "evidence": "P5_OVERLAP_GATE.json + P5P6_PIXEL_DIFF.json",
        },
        "exact_output_trim": "per segment the output frame count equals its source span (120/120/102/18), verified by ffprobe nb_read_frames; assembly = sum = 360",
    }

    failure_taxonomy = [
        {"id": "F1_GEOMETRY_CROP", "status": "FIXED_VERIFIED", "where": "P3 -> P3B",
         "defect": "the template's node 672:600 ResizeImageMaskNode hard-coded 482x854 crop=center so the latent was portrait and table/back-figure/partial person were cropped away (coverage FAIL)",
         "fix": "P3B_PAD ResizeAndPadImage 640x368 (area, centered) feeding 672:596/672:599/672:587.pose_video; 672:600 removed",
         "evidence": ["evidence/P3B_GRAPH.json", "evidence/P3B_RECEIPT.json", "evidence/P3B_GEOMETRY_GATE.json"]},
        {"id": "F2_PROMPT_CARRYOVER", "status": "FIXED_VERIFIED", "where": "P5 -> P5fix",
         "defect": "the BOOK prompt was copied into the TURN/OCC graphs (same prompt sha across all three) so the generated content was the book scene",
         "fix": "per-unit prompts (frozen; sha recorded per case)",
         "evidence": ["evidence/P5_TURN_OCC_GATE.json", "evidence/P5FIX_GATE.json"]},
        {"id": "F3_SEGMENT_AT_CUT", "status": "FIXED_VERIFIED", "where": "P5fix2 -> P5fix3",
         "defect": "the OCC window contains a cut at frame 102; the recorded [0,120) run/blind continuation failed on the second segment (rendered a document scene)",
         "fix": "split at the measured cut; OCC_SEG2 got its own anchor (anchor_occ_seg2_p5fix2, sha 81920361...) and its own prompt",
         "evidence": ["evidence/P5FIX2_CUT_SCAN.json", "evidence/P5FIX2_SPLIT.json", "evidence/P5FIX3_SEG2_RECEIPT.json"]},
        {"id": "F4_WATERMARK_COPY", "status": "OPEN_PRODUCT_BLOCKER", "where": "P4 (VACE path)",
         "defect": "VACE 14B fp16 copies the source's YouTube watermark (play button + 'Lạnh Vcl') at frames 0 and 119; Wan Animate 2 output has none",
         "impact": "the VACE path is not deliverable until a watermark-removal strategy is proven",
         "evidence": ["evidence/P4_GEOMETRY_GATE.json", "previews/p4_ab_*.png"]},
        {"id": "F5_BOOK_STATE", "status": "OPEN_PRODUCT_DECISION", "where": "BOOK case",
         "defect": "source event open_two_pages @72; Wan keeps the book CLOSED across the window, VACE shows it OPEN at f119",
         "impact": "needs a product decision; fidelity to the event is not achieved at this window on either profile",
         "evidence": ["evidence/P3B_GEOMETRY_GATE.json", "evidence/P4_GEOMETRY_GATE.json"]},
        {"id": "F6_RAM_INSTRUMENT", "status": "OPEN_INSTRUMENT", "where": "all GPU runs",
         "defect": "RAM peak NOT MEASURED: every sampler returned a non-credible ~5 MiB figure (tasklist and ctypes variants) for a server holding ~11 GB of weights",
         "impact": "RAM cost of the profile is unquantified; the number is reported as NOT MEASURED, never guessed",
         "evidence": ["evidence/P3B_RECEIPT.json:server_ram_peak_mib=5.7", "evidence/P6_NOCACHE_RECEIPT.json:server_ram_peak_mib=5.8"]},
        {"id": "F7_SEAM_FLAG_BOOK", "status": "FLAGGED_KEPT", "where": "BOOK case",
         "defect": "numeric join elevation 80->81 = 2.1582 and clip max 2.3195 at 85->86 vs p99 2.1692; read as motion-rate elevation (woman's arm rising), no visible seam",
         "impact": "flag kept; a reviewer can re-open previews/p5_overlap16_seam_strip.png",
         "evidence": ["evidence/P3B_GEOMETRY_GATE.json:seam", "evidence/P5_OVERLAP_GATE.json"]},
        {"id": "F8_TURN_TRANSIENT_GLYPH", "status": "RECORDED_KEPT", "where": "TURN case",
         "defect": "a transient doubled glyph at frame 60 of the accepted TURN clip",
         "impact": "recorded, not hidden; TURN coverage still PASS of its own segment",
         "evidence": ["evidence/P5FIX_GATE.json"]},
    ]

    parameters = [
        {"name": "anchor", "pointer": "graph/189/inputs/image", "type": "string",
         "rule": "file in the isolated server input dir; the per-shot anchor PNG (640x368 RGB)", "golden": "anchor_book_p2_00001_.png"},
        {"name": "source", "pointer": "graph/240/inputs/file", "type": "string",
         "rule": "driving window/segment mp4 (source span); 640x360, 30/1", "golden": "BOOK_src.mp4"},
        {"name": "prompt", "pointer": "graph/672:582/inputs/text", "type": "string",
         "rule": "frozen per-shot prompt (sha recorded per case)", "golden_sha256": prompts["BOOK"]["sha256"]},
        {"name": "seed", "pointer": "graph/672:597/inputs/noise_seed", "type": "int",
         "rule": "0 <= seed < 2^63; the BOOK golden seed is the accepted run's seed", "golden": 582699151003550},
        {"name": "filename_prefix", "pointer": "graph/246/inputs/filename_prefix|graph/292/inputs/filename_prefix", "type": "string",
         "rule": "output naming only; MUST NOT enter computation (same value both save nodes)", "golden": PREFIX},
        {"name": "length_source", "pointer": "graph/672:537 (GetImageSize of the loaded video) -> 672:636/672:639/672:667",
         "type": "derived", "rule": "chunking is derived from the loaded source, never typed by hand; 4n+1 node shape",
         "golden": "derived from the (120, 102, 18) frame spans"},
    ]

    graph_doc = {
        "schema_version": "mf.wan_shot.graph.v1",
        "graph_id": "wan_shot_v1",
        "generated_at_utc": stamp_for(OUT_GRAPH),
        "purpose": "Pinned Wan Animate 2 INT8 shot-reskin graph: source window (motion) + per-shot anchor (look) -> 640x368 clip with the source's own audio; the engine behind the measured profile.",
        "derived_from": {
            "template": {"file": "mf_animate2_book4s.shim.api.json", "path": TEMPLATE_PATH,
                         "sha256": TEMPLATE_SHA, "sha256_16": TEMPLATE_SHA[:16], "nodes": 64,
                         "note": "internal R27 wave-B shim template (no external license); the accepted P3B graph was built from it"},
            "accepted_predecessor_graph": {
                "file": "graphs/animate2_book.p3b.api.json",
                "sha256": rv["graphs/animate2_book.p3b.api.json"]["sha256_measured"],
                "nodes": 64, "cache": "on",
                "why": "P3b geometry fix accepted, BOOK coverage PASS (the first accepted clip of the wave)",
                "receipt": "evidence/P3B_RECEIPT.json", "prompt_id": "d1f4e097-458d-4bd4-8049-fe6da26f91c1"},
            "pinned_variant": {
                "name": "cache_off",
                "file": "graphs/animate2_book.p6nocache.api.json",
                "sha256": rv["graphs/animate2_book.p6nocache.api.json"]["sha256_measured"],
                "nodes": 63,
                "delta_from_predecessor": [
                    {"node": "672:594", "class_type": "WanAnimate2Cache", "action": "removed"},
                    {"node": "672:591", "class_type": "BasicScheduler", "input": "model", "was": ["672:594", 0], "now": ["672:588", 0]},
                    {"node": "672:592", "class_type": "ModelSamplingSD3", "input": "model", "was": ["672:594", 0], "now": ["672:588", 0]},
                ],
                "why": "measured faster AND lower VRAM AND pixel-identical to the cache-on run at the same seed (max_abs 0 over 120 frames), so the cache is dropped",
                "gate": "evidence/P6_NOCACHE_GATE.json",
            },
            "geometry_fix": {
                "pad_node": {"id": "P3B_PAD", "class_type": "ResizeAndPadImage", "target_width": 640, "target_height": 368,
                             "padding_color": "black", "interpolation": "area",
                             "semantics_source": "comfy_extras/nodes_images.py:594-641 (scale=min(fit), centered pad)"},
                "rewired": ["672:596 (GetImageSize)", "672:599 (ImageFromBatch)", "672:587 (WanAnimate2ToVideo.pose_video)"],
                "removed": {"id": "672:600", "class_type": "ResizeImageMaskNode",
                            "because": "hard-coded 482x854 crop=center (portrait latent)"},
                "why": "compose on the source aspect; the crop=center alternative would destroy the sides, and crop=disabled STRETCHES (measured node tooltip)",
                "evidence": "evidence/P3B_GRAPH.json + evidence/P3B_RECEIPT.json",
            },
            "node_semantics_measured": [
                {"claim": "WanAnimate2ToVideo consumes reference_image[:1]", "source": "nodes_wan.py:1253 (read; a 4-image batch does not mean 4 replacement roles)"},
                {"claim": "continuation uses 1 last frame + offset (not another model's overlap)", "source": "nodes_wan.py WanAnimate2ToVideo inputs (measured)"},
                {"claim": "video nodes use a 4n+1 frame shape", "source": "measured: VACE raw output 121 frames for a 120 request; Wan path trims to 120"},
                {"claim": "context overlap 8 vs 16 is inert on this shot", "source": "P5_OVERLAP_GATE (pixel-identical)"},
            ],
        },
        "runtime_pin": {
            "comfyui_version": RUNTIME["version"], "head": RUNTIME["head"], "porcelain_clean": True,
            "source_read_only": True, "models_root": RUNTIME["models_root"], "license": RUNTIME["license"],
            "isolation_recipe": "own base-directory (input/output/temp/user/custom_nodes pre-created; main.py::execute_prestartup_script lists custom_nodes before serving) + --models-directory at the shared read-only root + own port + --reserve-vram 1.0 --disable-auto-launch; one job at a time",
            "verification": "raw/evidence_reverify.json (HEAD + version-file sha + no listener on 8188/8189/8190/8310/8321/8342)",
        },
        "checkpoint_variant": {
            "note": "the pinned variant keeps the INT8 convrot checkpoint + the rank64 distill LoRA; other installed variants (bf16 animate, VACE 1.3B/14B, FLUX) are NOT this profile",
            "models": models_wan,
            "rejected_variants": [
                {"file": "diffusion_models/wan2.1_vace_14B_fp16.safetensors", "why": "challenger profile; watermark-copy blocker (F4)"},
                {"file": "diffusion_models/wan2.1_vace_1.3B_fp16.safetensors", "why": "installed but never ran in the proof; benchmark NOT RUN"},
            ],
        },
        "parameters": parameters,
        "cases": cases,
        "frame_mapping": frame_mapping,
        "failure_taxonomy": failure_taxonomy,
        "output_contract": {
            "nodes": ["246 (main clip, primary)", "292 (side-by-side composite, auxiliary)"],
            "files_per_run": 4,
            "main_dims": "640x368",
            "aux_dims": "1294x368 (stitched source|generated)",
            "naming": "<filename_prefix>_0000N_.mp4 under the run output dir; N=1 main, N=3 aux (N=2/4 are 1-frame stills the CreateVideo path also writes)",
            "audio": "carried from the loaded source by CreateVideo (672:245 / 291:80 feed audio from GetVideoComponents)",
        },
        "claims": {
            "quality_accepted": False,
            "quality_verdict_owner": "BENCH / DEMO / Codex",
            "no_best_newest_claim": "no claim of best/newest/fastest model; the profile is chosen from measured gates only",
            "quality_accepted_denominator": "accepted_seconds = 0 => cost per accepted second is UNDEFINED",
        },
        "graph": graph,
        "node_roles": {
            "189": "reference image (per-shot anchor; reference_image[:1])",
            "240": "driving video (source window/segment)",
            "246": "main clip output",
            "292": "side-by-side composite output (aux)",
            "672:578": "Wan Animate 2 INT8 convrot checkpoint loader",
            "672:579": "LightX2V rank64 distill LoRA",
            "672:580": "umt5 text encoder loader",
            "672:583": "clip_vision_h loader",
            "672:584": "Wan2.1 VAE bf16 loader",
            "672:590": "anchor resize to the reference geometry",
            "672:595": "source frames (+fps/audio) via GetVideoComponents",
            "672:596": "SIZE AUTHORITY: GetImageSize(P3B_PAD) -> node width/height",
            "672:599": "first padded drive frame for CLIP vision",
            "672:581": "negative prompt",
            "672:582": "positive prompt (per-shot, frozen)",
            "672:585": "camera/keep-viewpoint prompt",
            "672:589": "reference CLIP-vision conditioning",
            "672:598": "drive-frame CLIP-vision conditioning",
            "672:586": "ContextWindowsManual (cache-path split; bypassed in cache-off wiring)",
            "672:537": "source video size (drives all length math)",
            "672:636": "chunk-count math",
            "672:642": "chunk loop (StartLoop)",
            "672:645": "loop iterations = chunks + 1",
            "672:646": "length switch per chunk",
            "672:649": "loop item 0",
            "672:288": "source frames/audio/fps for the output video",
            "672:587": "WanAnimate2ToVideo (the model node; pose+reference+motion)",
            "672:588": "model-source switch (cache off => always the LoRA output)",
            "672:653": "loop item 1",
            "672:651": "offset switch",
            "672:591": "BasicScheduler (steps=6)",
            "672:592": "ModelSamplingSD3 (shift=5)",
            "672:593": "KSamplerSelect (lcm)",
            "672:635": "chunk_length primitive (81)",
            "672:639": "4n+1 length math",
            "672:652": "video_frame_offset switch",
            "672:654": "frame offset primitive (0)",
            "672:597": "SamplerCustom (seed/cfg)",
            "672:667": "final-batch shape predicate",
            "672:601": "VAEDecode",
            "672:602": "TrimVideoLatent (exact output trim)",
            "672:604": "drop-first-frame batch",
            "672:605": "loop output switch",
            "672:648": "loop accumulate list",
            "672:647": "EndLoop (accumulate)",
            "672:661": "RebatchImages",
            "672:670": "first-batch slice",
            "672:671": "final output switch",
            "672:245": "CreateVideo (fps/audio from source)",
            "291:78": "reference-side video components",
            "291:77": "generated-side video components",
            "291:90": "even-width math",
            "291:80": "CreateVideo for the composite",
            "291:290": "even-width math (ref)",
            "291:96": "even-height math",
            "291:79": "ImageStitch (source|generated)",
            "291:97": "composite resize",
            "291:416": "ref size",
            "291:417": "ref first frame",
            "291:571": "gen size",
            "291:572": "min dim",
            "291:573": "gen first frame",
            "P3B_PAD": "source-aspect pad to 640x368 (geometry fix; conditioning only)",
        },
    }

    # ---- manifest ----
    def rel_sha(rel: str) -> str:
        return rv[rel]["sha256_measured"]

    manifest = {
        "schema_version": "mf.wan_shot.manifest.v1",
        "graph_id": "wan_shot_v1",
        "generated_at_utc": stamp_for(OUT_MANIFEST),
        "workflow": {
            "graph_file": "app/media_workflows/wan_shot_v1.json",
            "graph_file_sha256": "<filled after write>",
            "graph_file_bytes": None,
            "graph_object_sha256": graph_object_sha,
            "node_count": len(graph),
            "template_file": "mf_animate2_book4s.shim.api.json",
            "template_path": TEMPLATE_PATH,
            "template_sha256": TEMPLATE_SHA,
            "template_sha256_16": TEMPLATE_SHA[:16],
            "accepted_predecessor_graph": {"file": "graphs/animate2_book.p3b.api.json", "sha256": rel_sha("graphs/animate2_book.p3b.api.json")},
            "pinned_variant_graph": {"file": "graphs/animate2_book.p6nocache.api.json", "sha256": rel_sha("graphs/animate2_book.p6nocache.api.json")},
            "graph_delta_vs_run_graph": "identical to graphs/animate2_book.p6nocache.api.json except nodes 246/292 filename_prefix (output naming only; does not enter computation)",
            "prompt_freeze": {k: {"sha256": v["sha256"], "chars": v["chars"], "node": v["node"], "text": v["text"]} for k, v in prompts.items()},
            "validation_offline": {
                "against": "P3_object_info_gpu.json (the pinned runtime's live /object_info captured on the GPU server with the shared read-only models root, 0.37.0)",
                "note": "P0_object_info.json (the same runtime WITHOUT the models root) carries empty/['pixel_space'] model-name option lists and must NOT be used for model-name validation — it produces a false negative",
                "rule": "every class_type + every recorded input name must exist; enum widgets must accept the value",
                "checked_by": "tests/product_delivery/test_mf_end_16.py",
            },
        },
        "models": models_wan + [model_vace],
        "runtime": {
            "comfyui_version": RUNTIME["version"], "head": RUNTIME["head"], "porcelain_clean": True,
            "source_read_only": True, "models_root": RUNTIME["models_root"], "license": RUNTIME["license"],
            "isolation_recipe": graph_doc["runtime_pin"]["isolation_recipe"],
            "reverified": "raw/evidence_reverify.json (2026-09-28)",
        },
        "inputs_frozen": {
            "note": "hashes re-measured on disk 2026-09-28 (MF-END-16); rows marked first_measurement had no prior record",
            "sources": [
                {"case": "BOOK", "rel": "inputs/BOOK_src.mp4", "sha256": rel_sha("inputs/BOOK_src.mp4"), "dims": [640, 360], "frames": 120, "fps": "30/1", "prior_record": "P3B_RECEIPT.inputs.driving"},
                {"case": "TURN", "rel": "inputs/TURN_795_src.mp4", "sha256": rel_sha("inputs/TURN_795_src.mp4"), "dims": [640, 360], "frames": 120, "fps": "30/1", "prior_record": "none (measured here)"},
                {"case": "OCC (window)", "rel": "inputs/OCC_14768_src.mp4", "sha256": rel_sha("inputs/OCC_14768_src.mp4"), "dims": [640, 360], "frames": 120, "fps": "30/1", "prior_record": "none (measured here)"},
                {"case": "OCC_SEG1", "rel": "inputs/p5fix2_occ_seg1.mp4", "sha256": rel_sha("inputs/p5fix2_occ_seg1.mp4"), "dims": [640, 360], "frames": 102, "fps": "30/1", "prior_record": "P5FIX2_SPLIT"},
                {"case": "OCC_SEG2", "rel": "inputs/p5fix2_occ_seg2.mp4", "sha256": rel_sha("inputs/p5fix2_occ_seg2.mp4"), "dims": [640, 360], "frames": 18, "fps": "30/1", "prior_record": "P5FIX2_SPLIT / P5FIX3_SEG2_SOURCE"},
            ],
            "anchors": [
                {"case": c["case_id"], "rel": c["anchor"]["rel"], "sha256": c["anchor"]["sha256"], "dims": c["anchor"]["dims"]} for c in cases
            ],
            "assembly_staging": [
                {"rel": s["path"], "sha256": s["sha256"], "byte_identical_to": s["expected_segment_sha"]}
                for s in load_json(RAW / "evidence_reverify.json")["staged_copies"]
            ],
        },
        "golden_runs": [
            {"case": c["case_id"], "prompt_id": c["receipt"]["prompt_id"], "graph": c["receipt"]["graph"],
             "graph_sha256": c["graph_evidence"]["sha256"], "cache": c["receipt"]["cache"],
             "server_side_wall_s": c["receipt"]["server_side_wall_s"],
             "seconds_per_output_second": c["receipt"]["seconds_per_output_second"],
             "vram_peak_mib": c["receipt"]["vram_peak_mib"],
             "output_main": c["output_main"]["file"], "output_main_sha256": c["output_main"]["sha256"],
             "receipt_file": c["receipt"]["file"], "gate_file": c["gate"]["file"]} for c in cases
        ] + [
            {"case": "BOOK_pinned_variant", "prompt_id": "06302bb4-68d1-4a48-be56-59c14451e100",
             "graph": "graphs/animate2_book.p6nocache.api.json", "graph_sha256": rel_sha("graphs/animate2_book.p6nocache.api.json"),
             "cache": "off", "server_side_wall_s": 135.21, "seconds_per_output_second": 33.8, "vram_peak_mib": 10763,
             "output_main": "output/p6_book_nocache/animate2_book_nocache_00001_.mp4",
             "output_main_sha256": rel_sha("output/p6_book_nocache/animate2_book_nocache_00001_.mp4"),
             "receipt_file": "evidence/P6_NOCACHE_RECEIPT.json", "gate_file": "evidence/P6_NOCACHE_GATE.json"},
            {"case": "ASSEMBLY_v13", "prompt_id": "e79a9cb7-9138-4117-90d3-b6c1defd3570",
             "graph": "graphs/p7_assembly_v13.api.json", "graph_sha256": rel_sha("graphs/p7_assembly_v13.api.json"),
             "server_side_wall_s": 1.15,
             "output_main": "output/p7/assembly_v13_00001_.mp4", "output_main_sha256": rel_sha("output/p7/assembly_v13_00001_.mp4"),
             "receipt_file": "evidence/P7_ASSEMBLY_V13.json", "gate_file": "evidence/P7_ASSEMBLY_V13_CHECK.json"},
            {"case": "VACE_challenger", "prompt_id": "402d0c10-fb71-44ca-9250-94029cc3366c",
             "graph": "graphs/animate2_vace_book.p4.api.json", "graph_sha256": rel_sha("graphs/animate2_vace_book.p4.api.json"),
             "cache": "n/a", "server_side_wall_s": 1174.24, "seconds_per_output_second": 291.13, "vram_peak_mib": 11680,
             "output_main": "output/p4/animate2_vace_book_p4_00001_.mp4",
             "output_main_sha256": rel_sha("output/p4/animate2_vace_book_p4_00001_.mp4"),
             "receipt_file": "evidence/P4_RECEIPT.json", "gate_file": "evidence/P4_GEOMETRY_GATE.json"},
        ],
        "measurement": {
            "unit": "seconds of server wall per second of generated video (s/output-second)",
            "cost_table": {
                "wan_cache_on_warm": {"server_side_wall_s": 154.67, "output_seconds": 4.0, "s_per_output_second": 38.67, "vram_peak_mib": 10973,
                                      "run": "P3B accepted BOOK; prompt_id d1f4e097"},
                "wan_cache_off_warm": {"server_side_wall_s": 135.21, "output_seconds": 4.0, "s_per_output_second": 33.8, "vram_peak_mib": 10763,
                                       "run": "P6 BOOK cache-off A/B; prompt_id 06302bb4; pixel-identical to the cache-on run"},
                "wan_cold": {"server_side_wall_s": 2387.78, "output_seconds": 4.0, "s_per_output_second": 596.95,
                             "provenance": "PROOF_LEDGER.jsonl collect row + P3B_RECEIPT.warm_run_note ('2387.78 s cold ... 596.95'); this is the canonical cold figure",
                             "second_recorded_wall": {"server_side_wall_s": 2394.31, "s_per_output_second": 598.58, "vram_peak_mib": 11897,
                                                      "provenance": "P3_RECEIPT.json own wall_s field (same run, prompt bbd21edd; +6.53 s boundary convention)"},
                             "caveat": "cold measured on the P3 first run, whose latent geometry was the portrait defect (480x848) later fixed in P3B; the accepted runs are all warm. Recorded as the only cold-start sample, never re-run."},
                "wan_cache_off_turn": {"server_side_wall_s": 134.94, "output_seconds": 4.0, "s_per_output_second": 33.73, "vram_peak_mib": 10855,
                                       "run": "P5fix TURN; prompt_id 4d4eda1b"},
                "wan_cache_off_occ_seg1": {"server_side_wall_s": 120.55, "output_seconds": 3.4, "s_per_output_second": 30.14, "vram_peak_mib": 10875,
                                           "run": "P5fix2 OCC_SEG1; prompt_id 4314671a",
                                           "note": "the receipt's per-second figure divides by the 4.0 s (120-frame) chunk window, not the trimmed 3.4 s span; kept verbatim"},
                "wan_cache_off_occ_seg2": {"server_side_wall_s": 31.21, "output_seconds": 0.6, "s_per_output_second": 7.8,
                                           "vram_peak_mib": 10931, "run": "P5fix3 OCC_SEG2; prompt_id 45eecffd",
                                           "note": "same denominator convention (4.0 s); a small clip is dominated by fixed server+load overhead, not a per-second rate"},
                "wan_warm_overlap16": {"server_side_wall_s": 155.0, "output_seconds": 4.0, "s_per_output_second": 38.75, "vram_peak_mib": 11224,
                                       "run": "P5 BOOK overlap-16 A/B (pixel-identical; the overlap knob is inert)"},
                "vace_14b_fp16": {"server_side_wall_s": 1174.24, "output_seconds": 4.033333, "s_per_output_second": 291.13, "vram_peak_mib": 11680,
                                  "run": "P4 BOOK challenger; prompt_id 402d0c10"},
                "assembly_graph": {"server_side_wall_s": 1.15, "output_seconds": 12.0, "note": "concat+audio in graph, no new sampling"},
            },
            "vram_summary": {
                "device_total_mib": 12227,
                "per_run_peaks_mib": {"p3_cold": 11897, "p3b_cache_on": 10973, "p6_cache_off": 10763, "p5_overlap16": 11224,
                                      "p5fix_turn": 10855, "p5fix2_seg1": 10875, "p5fix3_seg2": 10931, "vace_p4": 11680},
                "note": "the launch-packet shorthand '10,973 / 11,224 (cache off/on)' does not match the per-run evidence: 10973 is the cache-ON BOOK run and 11224 is the overlap-16 run; each run's own peak is listed here",
            },
            "ram_peak": {"status": "NOT_MEASURED", "samples_returned": "~5.7 MiB (non-credible; instrument F6)", "policy": "never substitute a guessed number"},
            "determinism": {
                "cache_on_vs_off": {"max_abs": 0, "mean_abs": 0.0, "frames_compared": 120, "verdict": "pixel-identical"},
                "overlap_8_vs_16": {"max_abs": 0, "mean_abs": 0.0, "frames_compared": 120, "verdict": "pixel-identical"},
                "evidence": "evidence/P5P6_PIXEL_DIFF.json",
                "caveat": "determinism is proven on THIS runtime/hardware; it is not a cross-machine byte guarantee (render seeds are not portable)",
            },
            "arithmetic_checks": [
                "154.67 / 4.0 = 38.6675 -> 38.67 (P3B receipt, 2dp)",
                "135.21 / 4.0 = 33.8025 -> 33.8 (P6 receipt)",
                "155.0 / 4.0 = 38.75 (P5 overlap-16 receipt)",
                "2387.78 / 4.0 = 596.945 -> 596.95 (canonical cold, ledger/warm-note)",
                "2394.31 / 4.0 = 598.5775 -> 598.58 (P3 receipt's own wall field for the same run)",
                "134.94 / 4.0 = 33.735 -> 33.73 (TURN)",
                "120.55 / 4.0 = 30.1375 -> 30.14 (OCC_SEG1; denominator = 4.0 s chunk window as recorded)",
                "31.21 / 4.0 = 7.8025 -> 7.8 (OCC_SEG2; same denominator convention)",
                "1174.24 / 4.033333 = 291.1345 -> 291.13 (VACE; denominator = its own 121/30 s raw clip)",
            ],
            "accepted_cost": {
                "accepted_seconds": 0,
                "reason": "QUALITY_ACCEPTED=0: no clip is quality-accepted yet, so the accepted-second denominator does not exist",
                "cost_per_accepted_second": "UNDEFINED",
                "policy": "do not fabricate a denominator; it becomes computable only when a quality owner accepts at least one second",
            },
        },
        "profile_decision": {
            "chosen_profile_id": "wan_animate2_int8_pad640x368_cacheoff",
            "benchmark_complete": True,
            "eligibility": "hard gates met on all four measured cases; quality acceptance reserved (BENCH/DEMO/Codex)",
            "challenger": {"profile_id": "vace_14b_fp16_book", "benchmark": "complete (technical)", "eligibility": "INELIGIBLE",
                           "blocker": "copies the source watermark (play button + 'Lạnh Vcl') at frames 0 and 119 (F4)"},
            "end17_note": "if the reviewer rejects the Wan candidate or requires the masked-edit path, END-17 activates: watermark-removal strategy for VACE and/or a new run per hypothesis",
            "registry": "app/media_workflows/model_profiles.json",
        },
        "failures_preserved": [f["id"] for f in failure_taxonomy],
        "evidence_root": str(RUN_ROOT),
        "claims": graph_doc["claims"],
    }

    profiles = {
        "schema_version": "mf.model_profiles.v1",
        "generated_at_utc": stamp_for(OUT_PROFILES),
        "engine": {"name": "ComfyUI", "version": RUNTIME["version"], "head": RUNTIME["head"],
                   "models_root": RUNTIME["models_root"], "license": RUNTIME["license"],
                   "isolation": graph_doc["runtime_pin"]["isolation_recipe"]},
        "profiles": [
            {
                "id": "wan_animate2_int8_pad640x368_cacheoff",
                "kind": "shot_reskin_video",
                "graph_id": "wan_shot_v1",
                "graph_file": "app/media_workflows/wan_shot_v1.json",
                "models": [
                    {"role": m["role"], "rel": m["rel"], "sha256": m["sha256"], "bytes": m["bytes"],
                     "license": m["license"], "source": m["source"]["repo"], "revision": m["source"]["revision"]}
                    for m in models_wan
                ],
                "params": {"steps": 6, "sampler": "lcm", "cfg": 1.0, "shift": 5,
                           "context_length": 21, "context_overlap": 8, "cache": "off",
                           "native_output_dims": [640, 368], "pad": "centered (4+4 rows over 640x360)",
                           "checkpoint_variant": "int8_convrot + rank64 distill LoRA"},
                "measured": {
                    "cold_s_per_output_second": 596.95,
                    "warm_s_per_output_second": 38.67,
                    "cache_off_s_per_output_second": 33.8,
                    "vram_peak_mib": 11224,
                    "ram_peak": "NOT_MEASURED",
                    "cases": ["BOOK", "TURN", "OCC_SEG1", "OCC_SEG2"],
                    "evidence": "app/media_workflows/wan_shot_v1.manifest.json#measurement",
                },
                "benchmark": {"status": "COMPLETE", "scope": "all four measured cases ran through this profile; each produced a real MP4 + receipt",
                              "note": "benchmark-complete != eligible"},
                "eligibility": {
                    "status": "ELIGIBLE_PENDING_QUALITY_OWNER",
                    "hard_gate_rows": [
                        {"gate": "dims 640x368", "verdict": "PASS", "evidence": "P3B_GEOMETRY_GATE / P5FIX_GATE / P5FIX3_GATE"},
                        {"gate": "timing (120/120/102/18 frames, 30/1, PTS monotonic)", "verdict": "PASS", "evidence": "per-case gates"},
                        {"gate": "coverage per segment (incl. partial right-edge person on BOOK)", "verdict": "PASS", "evidence": "per-case coverage previews + vision rows"},
                        {"gate": "holder/contact preserved (BOOK)", "verdict": "PASS", "evidence": "P3B coverage vision row"},
                        {"gate": "no watermark", "verdict": "PASS", "evidence": "per-case coverage vision rows"},
                        {"gate": "book-state equals the source event open_two_pages @72", "verdict": "OPEN (product decision F5)", "evidence": "P3B gate note"},
                        {"gate": "RAM peak quantified", "verdict": "OPEN (instrument F6)", "evidence": "receipts"},
                    ],
                    "quality_acceptance": "reserved to BENCH / DEMO / Codex (QUALITY_ACCEPTED=0)",
                },
                "cost": {"accepted_seconds": 0, "cost_per_accepted_second": "UNDEFINED",
                         "why": "no quality-accepted second exists yet; fabricating a denominator would be false"},
                "selection_rule": "chosen on measured hard gates, not on name/recency/time; speed never traded against fidelity (cache OFF is faster AND pixel-identical)",
            },
            {
                "id": "vace_14b_fp16_book",
                "kind": "shot_reskin_video",
                "graph_id": "animate2_vace_book.p4 (evidence)",
                "graph_file": "graphs/animate2_vace_book.p4.api.json",
                "models": [
                    {"role": "unet", "rel": "diffusion_models/wan2.1_vace_14B_fp16.safetensors", "sha256": model_vace["sha256"],
                     "bytes": model_vace["bytes"], "license": model_vace["license"],
                     "source": model_vace["source"]["repo"], "revision": model_vace["source"]["revision"]}
                ],
                "params": {"steps": 20, "sampler": "uni_pc", "cfg": 6.0, "shift": 8, "note": "measured run config (P4)"},
                "measured": {"s_per_output_second": 291.13, "vram_peak_mib": 11680, "ram_peak": "NOT_MEASURED",
                             "evidence": "evidence/P4_RECEIPT.json + evidence/P4_GEOMETRY_GATE.json"},
                "benchmark": {"status": "COMPLETE_TECHNICAL", "scope": "BOOK case only, same unit/seed as the Wan baseline"},
                "eligibility": {
                    "status": "INELIGIBLE",
                    "blockers": ["copies the source watermark (play button + 'Lạnh Vcl') at frames 0 and 119 (F4) — product blocker",
                                 "second segment/case never run on this profile"],
                    "quality_acceptance": "reserved to BENCH / DEMO / Codex",
                },
                "cost": {"accepted_seconds": 0, "cost_per_accepted_second": "UNDEFINED", "why": "same as above; additionally the profile is not deliverable"},
            },
        ],
        "selection": {
            "chosen": "wan_animate2_int8_pad640x368_cacheoff",
            "rationale": "the only profile with accepted-gate clips for all four measured segments; strictly faster AND lower-VRAM variant chosen among its own variants with pixel-identical evidence",
            "not_chosen": [{"id": "vace_14b_fp16_book", "why": "watermark-copy blocker (F4)"}],
            "end17_note": "no profile change is forced by speed; END-17 activates only if review rejects the Wan candidate or the masked-edit path is required",
            "decided_by": "MF-END-16 worker per packet 16.4 (eligibility measured here; quality acceptance reserved)",
        },
        "claims": {"quality_accepted": False, "no_best_newest_claim": True},
    }

    # ---- write graph + manifest (manifest needs the graph's file hash) ----
    if verify_only:
        results = []
        gb = OUT_GRAPH.read_bytes() if OUT_GRAPH.is_file() else b""
        want_manifest = copy.deepcopy(manifest)
        want_manifest["workflow"]["graph_file_sha256"] = sha256_bytes(gb)
        want_manifest["workflow"]["graph_file_bytes"] = len(gb)
        for path, doc in ((OUT_GRAPH, graph_doc), (OUT_MANIFEST, want_manifest), (OUT_PROFILES, profiles)):
            if not path.is_file():
                results.append({"file": path.name, "verdict": "MISSING"})
                continue
            text = json.dumps(doc, indent=1, ensure_ascii=False).replace("\n", "\r\n").encode("utf-8")
            got = path.read_bytes()
            results.append({"file": path.name, "verdict": "MATCH" if text == got else "DIFFER",
                            "bytes": len(got)})
        out = {"artifact": "determinism_check.json", "mode": "verify-modulo-timestamp",
               "at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "results": results}
        (RAW / "determinism_check.json").write_text(json.dumps(out, indent=1, ensure_ascii=False),
                                                    encoding="utf-8")
        bad = [r for r in results if r["verdict"] != "MATCH"]
        print(json.dumps({"verdict": "PASS" if not bad else "FAIL", "results": results}))
        return 0 if not bad else 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    g_bytes, g_sha = write_crlf_json(OUT_GRAPH, graph_doc)
    manifest["workflow"]["graph_file_sha256"] = g_sha
    manifest["workflow"]["graph_file_bytes"] = g_bytes
    m_bytes, m_sha = write_crlf_json(OUT_MANIFEST, manifest)
    p_bytes, p_sha = write_crlf_json(OUT_PROFILES, profiles)

    out = {
        "artifact": "build_record.json",
        "at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "files": [
            {"path": "app/media_workflows/wan_shot_v1.json", "bytes": g_bytes, "sha256": g_sha,
             "nodes": len(graph), "graph_object_sha256": graph_object_sha},
            {"path": "app/media_workflows/wan_shot_v1.manifest.json", "bytes": m_bytes, "sha256": m_sha},
            {"path": "app/media_workflows/model_profiles.json", "bytes": p_bytes, "sha256": p_sha},
        ],
        "prompt_shas": {k: v["sha256"] for k, v in prompts.items()},
        "graph_delta_vs_run_graph": sorted(differing),
    }
    (RAW / "build_record.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
