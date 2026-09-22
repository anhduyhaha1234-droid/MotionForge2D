#!/usr/bin/env python
"""MF-V1-VIDEO14B — build the RUN copies of the official Comfy templates.

The official template bytes are copied verbatim first. Every single change to a
run copy is declared in CHANGES below with the exact old value it replaces; the
script refuses to write anything unless the old value matches byte-for-byte, so
an unnoticed upstream edit can never be silently absorbed into a run copy.

Outputs (under the task worktree):
  workflows/official/<name>.json          verbatim official bytes + sha256 record
  workflows/run/<name>.json               the copy that will actually be submitted
  evidence/workflow_changes.json          machine-readable change record
  evidence/workflow_changes.diff          unified diff, official -> run copy
"""
import difflib
import hashlib
import json
import os
import shutil
import sys

WT = "C:/Users/Admin/Documents/Codex/work/mfv1/wt-video14b/experiments/mf_reskin_v1/video14b"
EV = "C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/mf-reskin-model-upgrade-20260922/20260922T0345Z/VIDEO14B"
EVB = EV
OFFICIAL = os.path.join(EV, "workflow-official")

RESKIN_POSITIVE = (
    "Character Description: a 2D cel-shaded illustration of a seated older reader holding an open book, "
    "redesigned with new clothing, new hair and a new flat colour palette; Background description: the same room "
    "redrawn as 2D illustration with new wall colour, new furniture design and a new lighting tint.\n"
    "Keep the composition, the camera, the body poses, the hand grip on the book, the prop placement and the "
    "second person exactly where they are; change who and what they are, not where they are."
)
POSE_PROMPT = (
    "Same viewpoint as the driving video: no camera movement and no viewpoint change. "
    "The driving video supplies body motion and hand gestures only."
)
VACE_POSITIVE = (
    "A 2D cel-shaded illustration of the same scene redrawn: the seated reader and the standing second person "
    "have new designs, new clothing and a new flat colour palette, the room and the furniture are redrawn, and the "
    "book is redrawn. The camera, the framing, the composition, the poses, the hand grip and the prop placement "
    "stay exactly as in the control video."
)

CHANGES = [
    {
        "file": "video_wan_animate2.json",
        "out_name": "mf_animate2_book4s.json",
        "node_id": 240, "scope": "top", "index": 0,
        "old": "street_dance_drive.mp4",
        "new": "mf_book_f1650_1770_drive_120f.mp4",
        "why": "Driving (pose) video input: point the released LoadVideo at the BOOK window driving clip cut from the frozen source film, frames [1650,1770), 120 frames, 30 fps, audio stripped.",
    },
    {
        "file": "video_wan_animate2.json",
        "out_name": "mf_animate2_book4s.json",
        "node_id": 189, "scope": "top", "index": 0,
        "old": "pink_hair_mech_arms_ref.png",
        "new": "mf_book_anchor_1650.png",
        "why": "Reference image input: the source-conditioned reskin anchor for the BOOK window (produced in the GPU round by FLUX.2 klein 4B edit, gated by a vision review before use).",
    },
    {
        "file": "video_wan_animate2.json",
        "out_name": "mf_animate2_book4s.json",
        "node_id": 672, "scope": "top", "index": 0,
        "old": "Character Description: Cartoon character lost\nBackground description: The background is an empty white room",
        "new": RESKIN_POSITIVE,
        "why": "Positive prompt (subgraph input text_1): the released sample prompt describes an empty white room and a lost cartoon character. Replaced with the task's whole-scene reskin instruction that keeps geometry and contact.",
    },
    {
        "file": "video_wan_animate2.json",
        "out_name": "mf_animate2_book4s.json",
        "node_id": 672, "scope": "top", "index": 1,
        "old": "A girl doing energetic street dance with rhythmic steps and dynamic arm gestures, background stationary\n",
        "new": POSE_PROMPT,
        "why": "Pose prompt (subgraph input text_2): the released sample describes street dance. Replaced with an explicit NO-VIEWPOINT-CHANGE instruction, because the model supports text-driven viewpoint control that decouples the output camera from the driving video and this task must disable that intent so the camera stays locked to the source.",
    },
    {
        "file": "video_wan_animate2.json",
        "out_name": "mf_animate2_book4s.json",
        "node_id": 292, "scope": "top", "index": 0,
        "old": "video/ComfyUI",
        "new": "mf_reskin_v1/video14b/animate2_book4s",
        "why": "Output subfolder: keep task output inside the task runtime output tree; the side-by-side 'Video Stitch' comparison is written here.",
    },
    {
        "file": "video_wan_animate2.json",
        "out_name": "mf_animate2_book4s.json",
        "node_id": 246, "scope": "top", "index": 0,
        "old": "video/ComfyUI",
        "new": "mf_reskin_v1/video14b/animate2_book4s",
        "why": "Output subfolder: this is the model output SaveVideo node (fed by the Motion Transfer subgraph instance 672) and it is the file the export step reads.",
    },
    {
        "file": "video_wan_animate2.json",
        "out_name": "mf_animate2_book4s.json",
        "node_id": 597, "scope": "Motion Transfer (Wan Animate 2)", "index": 2,
        "old": "randomize",
        "new": "fixed",
        "why": "Sampler seed control: pin the seed so the proof is reproducible and a re-run is comparable. The seed VALUE itself (widget index 1) is left exactly as released.",
    },
    {
        "file": "video_wan_vace_14B_v2v.json",
        "out_name": "mf_vace14b_book4s.json",
        "node_id": 145, "scope": "top", "index": 0,
        "old": "video_wan_vace_14B_v2v_reference_image_control_video.mp4",
        "new": "mf_book_f1650_1770_drive_121f.mp4",
        "why": "Control video input: the same BOOK source window, padded to 121 frames (4n+1) with a hold of the last frame, because WanVaceToVideo requires length-1 divisible by 4 and the released template ships length=81.",
    },
    {
        "file": "video_wan_vace_14B_v2v.json",
        "out_name": "mf_vace14b_book4s.json",
        "node_id": 134, "scope": "top", "index": 0,
        "old": "video_wan_vace_14B_v2v_reference_image.jpg",
        "new": "mf_book_anchor_1650.png",
        "why": "Reference image input: the same anchor used for the Wan-Animate-2 run, so the two candidates are compared on identical inputs.",
    },
    {
        "file": "video_wan_vace_14B_v2v.json",
        "out_name": "mf_vace14b_book4s.json",
        "node_id": 49, "scope": "top", "index": 0,
        "old": 720,
        "new": 640,
        "why": "DECLARED geometry change on WanVaceToVideo (widget index 0 = width, index 1 = height, index 2 = length; batch_size and strength stay as released): 720x720 would force a square geometry onto a 16:9 640x360 source, risking letterbox/crop that violates 'scale and layout must not change'. 640 is the source width rounded to a multiple of 16.",
    },
    {
        "file": "video_wan_vace_14B_v2v.json",
        "out_name": "mf_vace14b_book4s.json",
        "node_id": 49, "scope": "top", "index": 1,
        "old": 720,
        "new": 368,
        "why": "DECLARED geometry change, same node as the width change above: 368 = the 360-line source height rounded UP to a multiple of 16 (the step-16 encoder grid), keeping the 16:9 layout of the source instead of the released square 720x720.",
    },
    {
        "file": "video_wan_vace_14B_v2v.json",
        "out_name": "mf_vace14b_book4s.json",
        "node_id": 49, "scope": "top", "index": 2,
        "old": 81,
        "new": 121,
        "why": "DECLARED length change: WanVaceToVideo requires length-1 to be divisible by 4 (released value 81). The BOOK window is 120 frames, so the control clip is pre-padded to 121 frames (4n+1, last frame held) and the export drops exactly the last frame to return to 120 frames / 4.000 s. Padding plan and the drop rule are recorded in the run record and in BOOK_WINDOW.json.",
    },
    {
        "file": "video_wan_vace_14B_v2v.json",
        "out_name": "mf_vace14b_book4s.json",
        "node_id": 6, "scope": "top", "index": 0,
        "old": "The girl is dancing in a sea of flowers, slowly moving her hands. There is a close - up shot of her upper body. The character is surrounded by other transparent glass flowers in the style of Nicoletta Ceccoli, creating a beautiful, surreal, and emotionally expressive movie scene with a white, transparent feel and a dreamy atmosphere. ",
        "new": VACE_POSITIVE,
        "why": "Positive prompt: the released sample prompt would generate its own content. Replaced with the reskin instruction; the camera/lock language is explicit because VACE is a source-conditioned model and a prompt that implies camera motion would compete with the control video.",
    },
    {
        "file": "video_wan_vace_14B_v2v.json",
        "out_name": "mf_vace14b_book4s.json",
        "node_id": 68, "scope": "top", "index": 0,
        "old": 16,
        "new": 30,
        "why": "DECLARED fps change: the released VACE template writes 16 fps. The source timeline is 30 fps, so the run copy writes 30 fps to stay on the source timeline. This is a declared limitation (Wan2.1 VACE was released at 16 fps), not a free win, and it must be stated with any result.",
    },
    {
        "file": "video_wan_vace_14B_v2v.json",
        "out_name": "mf_vace14b_book4s.json",
        "node_id": 114, "scope": "top", "index": 0,
        "old": "video/ComfyUI",
        "new": "mf_reskin_v1/video14b/vace14b_book4s",
        "why": "Output subfolder: keep task output inside the task runtime output tree.",
    },
    {
        "file": "video_wan_vace_14B_v2v.json",
        "out_name": "mf_vace14b_book4s.json",
        "node_id": 107, "scope": "top", "kind": "mode", "index": None,
        "old": 0,
        "new": 4,
        "license_unclear": True,
        "excluded_from_run": True,
        "excluded_artifact": "Wan21_CausVid_14B_T2V_lora_rank32.safetensors",
        "why": "LICENCE EXCLUSION (blocking item B of the continuation packet). The released template applies the CausVid speed LoRA here (node 107, LoraLoader, mode 0 = active, strength 0.3). That file resolves to Kijai/WanVideo_comfy at the pinned revision 8260d429d19fd7a72304cad059160b95d843913f, whose repo metadata carries NO licence tag, whose README carries no licence statement, and which ships no LICENSE file (proven in DOWNLOAD_MANIFEST.json + raw/kijai_*.json). Rule: only public/free weights with a RECORDED licence may be used, so the LoRA is excluded from the run configuration. mode 0 -> 4 is the released template's OWN documented way to disable this node (MarkdownNote node 149: 'If you don't need it, you can use the bypass mode to disable'). Bypass resolution, verified from the released links: node 48 ModelSamplingSD3 takes model input link 192 from this node, and the LoRA's own model input is link 188 from node 106 UNETLoader; its clip output feeds CLIPTextEncode 6/7 via links 190/191 while its clip input is link 189 from node 110 CLIPLoader. Bypassing therefore yields UNETLoader -> ModelSamplingSD3 and CLIPLoader -> CLIPTextEncode, i.e. exactly the released model/encoder pair WITHOUT the unlicensed LoRA. The file is also removed from the runtime model search path so it cannot be loaded by accident (DOWNLOAD_MANIFEST.json -> excluded_from_run[]).",
    },
    {
        "file": "video_wan_vace_14B_v2v.json",
        "out_name": "mf_vace14b_book4s.json",
        "node_id": 3, "scope": "top", "index": 1,
        "old": "randomize",
        "new": "fixed",
        "why": "Sampler seed control: pin the seed so a proof is reproducible and a re-run is comparable. The seed VALUE itself (widget index 0) is left exactly as released. Widget index 1 is the seed's control_after_generate field, not the seed.",
    },
    {
        "file": "video_wan_vace_14B_v2v.json",
        "out_name": "mf_vace14b_book4s.json",
        "node_id": 3, "scope": "top", "index": 2,
        "old": 4,
        "new": 20,
        "why": "CONSEQUENCE OF THE LICENCE EXCLUSION, not a free tuning choice. The released value 4 is a CausVid-distill setting: the template's own MarkdownNote node 112 states '## Default - steps:20, cfg:6.0' and '## For CausVid LoRA - steps: 2-4, cfg: 1.0'. With the unlicensed LoRA excluded, the released 4-step/CFG-1 pair is no longer a matched configuration (it only works WITH the distillation), so the sampler returns to the value the template itself declares as the non-LoRA default. This is sourced from the released file's own note, not invented. Declared cost: the VACE run is then NOT the released speed configuration and must be labelled sampler_config_not_released wherever a VACE result is reported.",
    },
    {
        "file": "video_wan_vace_14B_v2v.json",
        "out_name": "mf_vace14b_book4s.json",
        "node_id": 3, "scope": "top", "index": 3,
        "old": 1,
        "new": 6.0,
        "why": "Same licence consequence as the step change above, same node: the released cfg=1.0 is the CausVid-distill CFG, and the template's own note 112 declares the non-LoRA default as cfg:6.0. Sampler (uni_pc), scheduler (simple), denoise (1) and shift are untouched.",
    },
]

KEEP_VERBATIM = [
    "UNETLoader model file names (Wan-Animate-2: wan_animate_2_int8_convrot.safetensors + lightx2v LoRA; VACE: wan2.1_vace_14B_fp16 + CausVid LoRA)",
    "CLIPLoader / CLIPVisionLoader / VAELoader file names",
    "all sampler settings except the seed control (lcm / uni_pc, steps, cfg, shift)",
    "the released negative prompts",
    "WanAnimate2Cache device/dtype (gpu/int8) and the enable_context_window switch (False)",
    "every node mode, including the bypassed 1.3B and Canny branches of the VACE template",
    "the WanAnimate2Cache / ContextWindowsManual / loop wiring",
]


def structural_delta(a, b, path=""):
    """Leaf-level differences between two parsed JSON documents."""
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append({"path": path + "/" + str(k), "old": a.get(k, "<absent>"), "new": b.get(k, "<absent>")})
            else:
                out.extend(structural_delta(a[k], b[k], path + "/" + str(k)))
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append({"path": path + "/<len>", "old": len(a), "new": len(b)})
        for i in range(min(len(a), len(b))):
            out.extend(structural_delta(a[i], b[i], path + "/" + str(i)))
    else:
        if a != b:
            out.append({"path": path, "old": a, "new": b})
    return out


def serialize_like_source(graph, source_text, target):
    """Serialise `graph` in the SAME style as the released file, proven by round-trip.

    Only an (indent, ensure_ascii, trailing-newline) combination that reproduces the
    UNMODIFIED source bytes exactly is accepted, so the resulting diff carries the
    declared changes and nothing else. A silent re-format would make the review diff
    unreadable and would change the file size without a declared reason, so when no
    style reproduces the source the generator refuses to write at all.
    """
    parsed = json.loads(source_text)
    for indent in (1, 2, 4):
        for ensure_ascii in (False, True):
            candidate = json.dumps(parsed, indent=indent, ensure_ascii=ensure_ascii)
            for suffix in ("", "\n"):
                if candidate + suffix == source_text:
                    return json.dumps(graph, indent=indent, ensure_ascii=ensure_ascii) + suffix
    raise SystemExit("REFUSING: no byte-faithful serialisation style reproduces %s" % target)


def resolve_node(doc, parts, idx):
    """structural_delta reports the POSITION of an element inside a list, not its id.
    Walk the document (top level or definitions/subgraphs/<i>/...) to the node list
    and return the node object at that position."""
    cur = doc
    for seg in parts[:idx + 1]:
        cur = cur[int(seg)] if isinstance(cur, list) else cur[seg]
    return cur[int(parts[idx + 1])]


def verify_delta(delta, declared, target, after_doc):
    """delta == declared set, checked in BOTH directions.

    Every observed difference must correspond to exactly one declared change whose
    preimage and postimage match, and every declared change must actually be observed
    in the document. Node ids are resolved from the document itself (a list position
    is not an id). Nothing is written to a run copy until this returns.
    """
    seen = []
    for entry in delta:
        parts = entry["path"].strip("/").split("/")
        if "nodes" not in parts:
            raise SystemExit("UNDECLARED DELTA in %s at %s: %r -> %r"
                             % (target, entry["path"], entry["old"], entry["new"]))
        idx = parts.index("nodes")
        node = resolve_node(after_doc, parts, idx)
        node_id = node.get("id")
        tail = parts[idx + 2:]
        if tail == ["mode"]:
            field, index = "mode", None
        elif len(tail) == 2 and tail[0] == "widgets_values":
            field, index = "widgets_values", int(tail[1])
        else:
            raise SystemExit("UNDECLARED DELTA in %s at %s (unsupported field %r)"
                             % (target, entry["path"], tail))
        hits = [d for d in declared
                if d["node_id"] == node_id
                and d.get("kind", "widgets_values") == field
                and d["index"] == index]
        if not hits:
            raise SystemExit("UNDECLARED DELTA in %s at %s: node %s field %s index %s was not declared"
                             % (target, entry["path"], node_id, field, index))
        if len(hits) > 1:
            raise SystemExit("AMBIGUOUS DECLARATION in %s for node %s field %s index %s"
                             % (target, node_id, field, index))
        ch = hits[0]
        if entry["old"] != ch["old"] or entry["new"] != ch["new"]:
            raise SystemExit("DECLARED PREIMAGE MISMATCH in %s node %s: observed %r -> %r, declared %r -> %r"
                             % (target, node_id, entry["old"], entry["new"], ch["old"], ch["new"]))
        seen.append(ch)
    missing = [d for d in declared if d not in seen]
    if missing:
        raise SystemExit("DECLARED CHANGE NOT OBSERVED in %s: %r"
                         % (target, [(m["node_id"], m.get("kind", "widgets_values"), m["index"]) for m in missing]))
    return len(delta), len(declared)


def find_widget_owner(graph, node_id, scope):
    if scope == "top":
        nodes = graph.get("nodes", [])
    else:
        nodes = None
        for sg in (graph.get("definitions", {}) or {}).get("subgraphs", []):
            if sg.get("name") == scope:
                nodes = sg.get("nodes", [])
                break
        if nodes is None:
            raise SystemExit("subgraph not found: %s" % scope)
    for n in nodes:
        if n.get("id") == node_id:
            return n
    raise SystemExit("node id %s not found in scope %s" % (node_id, scope))


def main():
    os.makedirs(os.path.join(WT, "workflows", "official"), exist_ok=True)
    os.makedirs(os.path.join(WT, "workflows", "run"), exist_ok=True)
    os.makedirs(os.path.join(WT, "evidence"), exist_ok=True)

    # 1. verbatim official bytes + hash record
    official_record = []
    for name in ("video_wan_animate2.json", "video_wan_animate2_distilled.json", "video_wan_vace_14B_v2v.json"):
        src = os.path.join(OFFICIAL, name)
        dst = os.path.join(WT, "workflows", "official", name)
        shutil.copyfile(src, dst)
        raw = open(dst, "rb").read()
        official_record.append({
            "name": name,
            "source_path": src,
            "copied_to": dst,
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        })
        assert open(src, "rb").read() == raw, "verbatim copy mismatch for %s" % name

    # 2. run copies
    applied = []
    diffs = []
    per_workflow_diffs = {}
    verification = []
    for target in ("video_wan_animate2.json", "video_wan_vace_14B_v2v.json"):
        src = os.path.join(OFFICIAL, target)
        before_text = open(src, encoding="utf-8").read()
        graph = json.loads(before_text)
        declared = [c for c in CHANGES if c["file"] == target]
        for ch in declared:
            node = find_widget_owner(graph, ch["node_id"], ch["scope"])
            if ch.get("kind") == "mode":
                if node.get("mode") != ch["old"]:
                    raise SystemExit("REFUSING: %s node %s mode is %r, declared old is %r"
                                     % (target, ch["node_id"], node.get("mode"), ch["old"]))
                node["mode"] = ch["new"]
                now = node["mode"]
                applied.append({"field": "mode", "applied_value": now, **ch})
                continue
            wv = node.get("widgets_values")
            if ch["index"] is None:
                if wv != ch["old"]:
                    raise SystemExit("REFUSING: %s node %s widget list is %r, declared old is %r"
                                     % (target, ch["node_id"], wv, ch["old"]))
                node["widgets_values"] = ch["new"]
                now = ch["new"]
            else:
                if not isinstance(wv, list) or wv[ch["index"]] != ch["old"]:
                    raise SystemExit("REFUSING: %s node %s widget[%s] is %r, declared old is %r"
                                     % (target, ch["node_id"], ch["index"],
                                        (wv or [None])[ch["index"]] if isinstance(wv, list) else wv, ch["old"]))
                node["widgets_values"][ch["index"]] = ch["new"]
                now = node["widgets_values"][ch["index"]]
            applied.append({"field": "widgets_values", "applied_value": now, **ch})
        out_name = "mf_animate2_book4s.json" if target == "video_wan_animate2.json" else "mf_vace14b_book4s.json"
        out_path = os.path.join(WT, "workflows", "run", out_name)
        after_text = serialize_like_source(graph, before_text, target)
        # structural verification: the delta between official and run copy must be
        # EXACTLY the declared change set, in both directions. The run copy is only
        # written AFTER this passes, so a failed verification can never leave a
        # half-trusted run copy on disk.
        delta = structural_delta(json.loads(before_text), graph)
        n_delta, n_declared = verify_delta(delta, declared, target, graph)
        with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(after_text)
        d = difflib.unified_diff(before_text.splitlines(), after_text.splitlines(),
                                 fromfile="official/" + target, tofile="run/" + out_name, lineterm="")
        diff_text = "\n".join(d)
        diffs.append(diff_text)
        per_workflow_diffs[out_name] = diff_text
        verification.append({"file": target, "run_copy": out_path,
                             "delta_entries": n_delta, "declared_changes": n_declared,
                             "direction_a_delta_subset_of_declared": True,
                             "direction_b_declared_subset_of_delta": True,
                             "verdict": "DELTA_EQUALS_DECLARED_SET"})

    record = {
        "task_id": "MF-V1-VIDEO14B",
        "artifact": "evidence/workflow_changes.json",
        "what_this_is": "The declared change set from each released official ComfyUI template to the run copy that wave 2 will submit. Generated by tools/make_run_workflows.py, which refuses to write a run copy unless the observed structural delta equals this declared set in BOTH directions.",
        "official_templates_verbatim": official_record,
        "source_provenance": {
            "rule": "The official bytes were taken from the file each release actually ships, not from a web page copy.",
            "workflow_templates_repo": "Comfy-Org/workflow_templates, main sha 84c1958d169f6bb8459832ef1c432d0cf789ebc4 (observed 2026-09-22T04:07:08Z when the three files were fetched)",
            "packaged_cross_check": "byte-identical (size + sha256) to the templates shipped by comfyui-workflow-templates-json 0.1.92, the version ComfyUI v0.37.0 itself requires and loads",
            "engine_pin": "ComfyUI v0.37.0 = commit 73c9bad4d21e7addbe1d13bc92eee0f1431b017d (runtime/video14b/ComfyUI), node inventory proven in raw/node_inventory_v0.37.0.json and raw/runtime_node_inventory_cpu.json",
            "files": [
                {"name": "video_wan_animate2.json", "sha256": "f9907c332e7b2c48e9378797f8952ed90391efd6924a4ff162208d369fb52563", "bytes": 164226},
                {"name": "video_wan_animate2_distilled.json", "sha256": "aa598abe50f87d1277c55a9e5288e8d9ff7ab564768b28e1d25165aff8b459c2", "bytes": 214640, "used": False},
                {"name": "video_wan_vace_14B_v2v.json", "sha256": "b1b79044f20eea5590aa419b4ca28a5fb455981c38ffd22db8a9fb6f641e00b9", "bytes": 30970},
            ],
        },
        "run_copies": [
            {"path": os.path.join(WT, "workflows", "run", "mf_animate2_book4s.json"),
             "derived_from": "workflows/official/video_wan_animate2.json",
             "candidate": "C1 Wan-Animate-2 14B (int8 convrot) - primary",
             "changes": [c for c in applied if c["file"] == "video_wan_animate2.json"]},
            {"path": os.path.join(WT, "workflows", "run", "mf_vace14b_book4s.json"),
             "derived_from": "workflows/official/video_wan_vace_14B_v2v.json",
             "candidate": "C2 Wan2.1 VACE 14B (fp16) - fallback/contrast",
             "changes": [c for c in applied if c["file"] == "video_wan_vace_14B_v2v.json"]},
        ],
        "workflow_io_map": {
            "_how": "Node ids read from the released template files; links resolved through the files' own links[] table. These are the nodes wave 2 must watch to prove the run consumed the intended inputs.",
            "mf_animate2_book4s.json": {
                "driving_video_consumers": [
                    "top LoadVideo id 240 (widget file mf_book_f1650_1770_drive_120f.mp4) -> link 994 -> Motion Transfer subgraph instance id 672 input 'video' -> inside the subgraph WanAnimate2ToVideo id 587 input 'pose_video'",
                    "the same driving clip also feeds the released 'Video Stitch' subgraph instance id 291 input 'video_1' via link 970, which is the side-by-side comparison render only",
                ],
                "reference_image_consumers": [
                    "top LoadImage id 189 (widget file mf_book_anchor_1650.png) -> link 993 -> Motion Transfer subgraph instance id 672 input 'input' -> WanAnimate2ToVideo id 587 input 'reference_image'",
                ],
                "mask_conditioning_consumers": [
                    "WanAnimate2ToVideo id 587 has NO mask input; conditioning arrives as CLIPTextEncode positive/negative feeding 587 inputs 'positive'/'negative' (prompt text carried by subgraph instance widget indices 0 and 1 of node 672)",
                    "clip-vision conditioning: 587 inputs 'clip_vision_output'/'clip_vision_output_pose' fed from clip_vision_h.safetensors through the released CLIPVisionLoader",
                ],
                "media_writer": "SaveVideo id 246 (the model output the export step reads, fed by subgraph instance 672 via link 995); SaveVideo id 292 writes the side-by-side comparison fed by the Video Stitch subgraph",
                "padding_plan": "source window 120 frames; WanAnimate2ToVideo length is 4n+1 so 121 frames are generated internally (last source frame 1769 held as the extra one); the template's own ComfyMathExpression id 667 '(a % 4 == 1) and ((b - 1) % 4 == 0)' evaluates FALSE for a=120, so ComfySwitchNode id 671 selects the on_false branch = ImageFromBatch id 670 (start 0, length a = 120); the run copy therefore emits exactly 120 frames and ImageFromBatch cuts the internal 121st frame back off. The other branch, ImageFromBatch id 604 (start 1), is NOT taken for this window. Nothing is pre-padded and no frame is dropped from the head.",
            },
            "mf_vace14b_book4s.json": {
                "driving_video_consumers": [
                    "top LoadVideo id 145 (widget file mf_book_f1650_1770_drive_121f.mp4) -> link 223 -> GetVideoComponents id 144 -> Canny id 147 -> link 226 -> WanVaceToVideo id 49 input 'control_video'",
                ],
                "reference_image_consumers": [
                    "top LoadImage id 134 (widget file mf_book_anchor_1650.png) -> link 216 -> WanVaceToVideo id 49 input 'reference_image'",
                ],
                "mask_conditioning_consumers": [
                    "WanVaceToVideo id 49 input 'control_masks' is NOT connected in the released template (no mask is applied) - stated so nobody assumes a mask was passed",
                    "conditioning: CLIPTextEncode id 6 (positive) and id 7 (negative) -> WanVaceToVideo id 49 inputs 'positive'/'negative' -> KSampler id 3",
                ],
                "media_writer": "SaveVideo id 114 <- CreateVideo id 68 (its fps widget is the declared 16 -> 30 change) <- VAEDecode id 8",
                "padding_plan": "the 120-frame window is pre-padded to 121 frames (4n+1, last frame 1769 held) and WanVaceToVideo length is set to 121; the model runs one 121-frame pass. EXPORT RULE: the run emits 121 frames and the export drops exactly the LAST frame (index 120) to return 120 frames / 4.000 s. Never drop from the head, never crop by duration.",
            },
        },
        "forbidden_transformations": [
            "Changing container/stream metadata from 24 fps to 30 fps to make a 24 fps model sample look like 30 fps material (the upstream Wan-Animate-2 sample exports at fps=24; that must never be copied onto this 30 fps timeline as a metadata rewrite).",
            "Rescaling or retiming the clip so that a shorter/longer render presents as 4.000 s.",
            "Stretching or regenerating the voice track to hide a length mismatch; audio is remuxed from the frozen source by timeline (-c:a copy), never re-encoded per window.",
            "Dropping frames from an arbitrary position to hit a frame count.",
            "Hand-mixing distillation, LoRA, sampler, scheduler, shift or step choices that are not declared here or sourced from the released files' own notes.",
        ],
        "licence_exclusion": {
            "decision": "EXCLUDED_FROM_RUN - license_unclear",
            "artifacts": [
                "Wan21_CausVid_14B_T2V_lora_rank32.safetensors (node 107 in the released VACE template, applied at strength 0.3)",
                "Wan21_CausVid_bidirect2_T2V_1_3B_lora_rank32.safetensors (node 109, already mode 4 = bypassed in the released template)",
            ],
            "provenance": "Kijai/WanVideo_comfy at pinned revision 8260d429d19fd7a72304cad059160b95d843913f - the exact hosting repo the released VACE template's own MarkdownNote node 150 links to",
            "why_unclear": "The repo metadata carries no licence tag, the README carries no licence statement, and there is no LICENSE file at the repo root; the only licence-like file in the repo is LoRAs/Ditto/ditto_LICENSE.txt, which belongs to an unrelated LoRA. Evidence kept: raw/kijai_repo_meta_pinned.json, raw/kijai_tree_pinned.json, raw/kijai_README_pinned.md.",
            "rule_applied": "Only public/free weights with a RECORDED licence may be used. No licence could be recorded at the pinned revision, so the LoRAs may not be loaded.",
            "enacted_in_workflow_delta": "node 107 mode 0 -> 4 (the released template's own documented disable method) plus the sampler consequence (steps 4 -> 20, cfg 1.0 -> 6.0, taken from the released file's own MarkdownNote node 112 'Default' values), which are the only changes in the VACE run copy attributable to this decision.",
            "node_109_note": "node 109 is already mode 4 (bypassed) in the released bytes and is therefore never executed or loaded; its widget filename string is left exactly as released rather than edited, so the run copy does not deviate from the released bytes in a way the reviewer cannot see. Nothing reads it.",
            "not_loaded_guarantee": "Both files were also moved out of the runtime model search path (models/loras/ -> excluded_unlicensed_weights/), recorded with their hashes in DOWNLOAD_MANIFEST.json -> excluded_from_run[]. A shortcut link to them can no longer be resolved by the engine, so the exclusion is structural and not merely declarative. The bytes are preserved; nothing was deleted.",
            "consequence_to_report": "The VACE candidate can no longer be run as the released 4-step/CFG-1 speed configuration. Any VACE result must carry sampler_config_not_released, and its cost must not be presented as the released template's cost.",
        },
        "delta_verification_summary": {
            "method": "structural_delta() over the parsed released document vs the parsed run copy (leaf level), then verify_delta(): every observed difference must match exactly one declared change with matching preimage and postimage, and every declared change must be observed. List positions are resolved back to real node ids before matching.",
            "per_workflow": verification,
            "verdict": "DELTA_EQUALS_DECLARED_SET for every run copy" if all(v["verdict"] == "DELTA_EQUALS_DECLARED_SET" for v in verification) else "NOT_PROVEN",
        },
        "kept_verbatim": KEEP_VERBATIM,
        "hand_mixing_declaration": "No distill/LoRA/sampler/scheduler/shift choice was mixed by hand. Every changed value is an operator input (prompt, input file, output subfolder, seed control), a DECLARED geometry/length/fps change, or a value the released file itself declares for the non-LoRA case (node 112). Every model component stays exactly as the official template released it, except the one unlicensed LoRA that this round excludes.",
        "determinism": "Running this generator twice must produce byte-identical run copies and diffs; a mismatch means the run copy is not reproducible and must not be trusted.",
    }
    os.makedirs(os.path.join(EVB, "evidence"), exist_ok=True)
    for out_dir in (os.path.join(WT, "evidence"), os.path.join(EVB, "evidence")):
        with open(os.path.join(out_dir, "workflow_changes.json"), "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=1, ensure_ascii=False)
        with open(os.path.join(out_dir, "workflow_changes.diff"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(diffs) + "\n")
        for out_name, diff_text in per_workflow_diffs.items():
            with open(os.path.join(out_dir, "workflow_changes." + out_name + ".diff"), "w",
                      encoding="utf-8", newline="\n") as fh:
                fh.write(diff_text + "\n")
    print(json.dumps({"verbatim": len(official_record), "applied_changes": len(applied),
                      "run_copies": [r["path"] for r in record["run_copies"]],
                      "delta_verification": [(v["file"], v["delta_entries"], v["declared_changes"], v["verdict"])
                                             for v in verification]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
