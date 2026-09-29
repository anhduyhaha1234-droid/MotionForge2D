"""DELTA-F2 — byte-exact bounded patch for app/adapters/media_engine/comfy.py.

The file is CRLF (984 CRLF / 984 LF, no BOM) and ``core.autocrlf=true``: every
replacement is applied as BYTES with an exact single-occurrence assertion, per the
CRLF pitfall (fuzzy patching on CRLF silently eats adjacent lines).

Run:  python.exe tools/apply_delta_f2_patch.py [--check]
"""
from __future__ import annotations

import sys
from pathlib import Path

WT = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/DELTA-F2")
TARGET = WT / "app" / "adapters" / "media_engine" / "comfy.py"
CRLF = "\r\n"


def _block(text: str) -> bytes:
    body = text.strip("\n").replace("\n", CRLF) + CRLF
    return body.encode("utf-8")


# ── 1. module docstring: the measured terminal media shape ────────────────────

A1 = _block(
    "set for artifact kinds the contract allows to ever be published; acceptance/\n"
    "publication themselves stay with the app (S10/S12)."
)
R1 = _block(
    "set for artifact kinds the contract allows to ever be published; acceptance/\n"
    "publication themselves stay with the app (S10/S12).\n"
    "\n"
    "Terminal media shape (measured; DELTA-F2): a terminal node's result is recorded\n"
    "under a bucket whose NAME moved between ComfyUI versions.  On 0.37.0 (pin\n"
    "73c9bad4; MF-DEMO-E2E ``raw/history_shot1.json``, prompt ``f8f000f9-``…, status\n"
    "success) the ``SaveVideo`` node returns ``ui.PreviewVideo``, whose\n"
    "``as_dict()`` is ``{\"images\": […], \"animated\": (True,)}`` — a RENDERED VIDEO\n"
    "lands in the ``images`` bucket flagged animated — while other pins publish a\n"
    "real ``videos`` bucket.  The pinned engine can pin only ONE bucket per declared\n"
    "node (and its own ``_MEDIA_OF_KIND`` table refuses ``images`` + ``video``), so\n"
    "a terminal video is declared in the engine's server-decides form (empty bucket\n"
    "+ the measured media family) and the app classifies what the server actually\n"
    "published: a ``videos`` entry is the video (legacy pins, kept), and an\n"
    "``images``/``gifs`` entry counts as the video only when the server flagged it\n"
    "``animated`` (the 0.37 shape) and the container is a video container.  An\n"
    "animation-bucket entry without that proof is never classified as the video the\n"
    "terminal declared: the record keeps the bytes, and the caller's main-artifact\n"
    "gate refuses the shot instead of accepting an unproven shape."
)

# ── 2. terminal maps + measured shape tables ─────────────────────────────────

A2 = _block(
    '_TERMINAL_KIND_MAP = {"image": ("images", "image"), "video": ("videos", "video"),\n'
    '                      "audio": ("audio", "audio")}\n'
    '_ENGINE_KIND_TO_APP = {"images": "image", "gifs": "image", "videos": "video", "audio": "audio"}'
)
R2 = _block(
    "#: App terminal kind → the engine declaration this node is submitted with.\n"
    "#: ``image``/``audio`` pin the bucket their measured pins publish into.\n"
    "#: ``video`` declares the engine's server-decides form (empty bucket) because\n"
    "#: the bucket a pinned ComfyUI writes a video into moved between versions (see\n"
    "#: the module docstring) and the engine's own contract table refuses ``images``\n"
    "#: + ``video``.  The media family stays pinned — the engine checks it against\n"
    "#: the suffix of the file it stages.\n"
    '_TERMINAL_KIND_MAP = {"image": ("images", "image"), "video": ("", "video"),\n'
    '                      "audio": ("audio", "audio")}\n'
    '_ENGINE_KIND_TO_APP = {"images": "image", "gifs": "image", "videos": "video", "audio": "audio"}\n'
    "\n"
    "#: Buckets in which ComfyUI publishes an ALREADY-ENCODED animation: the measured\n"
    "#: 0.37 SaveVideo shape lands in ``images`` with ``animated`` set.  A pin that\n"
    "#: publishes a real ``videos`` bucket is handled by ``_ENGINE_KIND_TO_APP``.\n"
    '_ANIMATION_BUCKETS = ("images", "gifs")\n'
    "\n"
    "#: Containers the pinned engine stages as video (mirrors its ``VIDEO_SUFFIXES``\n"
    "#: at MF-COMFY R28 / 70f7180): the app never classifies an artifact as a video\n"
    "#: that the engine would not have staged as one.\n"
    '_VIDEO_CONTAINER_SUFFIXES = (".mp4", ".webm", ".mkv", ".mov", ".avi", ".gif")'
)

# ── 3. _normalize_terminal_outputs docstring ─────────────────────────────────

A3 = _block(
    "    App kinds are ``image`` / ``video`` / ``audio``; the engine keys artifacts by\n"
    "    ComfyUI bucket (``images`` / ``videos`` / ``audio``) and checks the declared\n"
    "    ``media_type`` against the filename suffix it staged.\n"
    '    """'
)
R3 = _block(
    "    App kinds are ``image`` / ``video`` / ``audio``; the engine keys artifacts by\n"
    "    ComfyUI bucket and checks the declared ``media_type`` against the filename\n"
    "    suffix it staged.  A video terminal declares the engine's server-decides form\n"
    "    (empty bucket + ``media_type video``) because the bucket a pinned ComfyUI\n"
    "    publishes a video into is version detail (``videos`` on older pins,\n"
    "    ``images`` + animated on 0.37 — see the module docstring) while the video\n"
    "    media family is what must hold.  An empty kind is the engine's own normalized\n"
    "    form for a node whose media the server output decides, so the declaration\n"
    "    stays a contract the pinned engine validates instead of a guess.\n"
    '    """'
)

# ── 4. module-level helpers (inserted after _safe_component) ─────────────────

A4 = _block(
    'def _safe_component(value: str) -> str:\n'
    '    return re.sub(r"[^0-9A-Za-z._-]", "_", value or "") or "unknown"'
)
R4 = _block(
    'def _safe_component(value: str) -> str:\n'
    '    return re.sub(r"[^0-9A-Za-z._-]", "_", value or "") or "unknown"\n'
    "\n"
    "\n"
    'def _published_animation_proof(entry: dict, node_ids: set[str]) -> set[tuple[str, str]]:\n'
    '    """``{(bucket, filename)}`` this history entry flags ``animated`` on the nodes.\n'
    "\n"
    "    ComfyUI publishes a node's UI output as ``{bucket: [items…], \"animated\":\n"
    "    [bool, …]}`` with the flags aligned to the bucket list — measured on 0.37.0,\n"
    "    where ``comfy_api.latest._ui.PreviewVideo.as_dict()`` returns\n"
    "    ``{\"images\": […], \"animated\": (True,)}`` for SaveVideo.  Only an aligned,\n"
    "    explicitly-true flag is proof: a missing/short flag list or a false flag is an\n"
    "    UNPROVEN shape and is never upgraded to the video a terminal declared.\n"
    '    """\n'
    '    outputs = (entry or {}).get("outputs")\n'
    "    if not isinstance(outputs, dict):\n"
    "        return set()\n"
    "    proven: set[tuple[str, str]] = set()\n"
    "    for node_id in sorted(node_ids):\n"
    '        node_out = outputs.get(str(node_id))\n'
    "        if not isinstance(node_out, dict):\n"
    "            continue\n"
    '        flags = node_out.get("animated")\n'
    "        if not isinstance(flags, (list, tuple)):\n"
    "            continue\n"
    "        for bucket in _ANIMATION_BUCKETS:\n"
    '            items = node_out.get(bucket)\n'
    "            if not isinstance(items, list):\n"
    "                continue\n"
    "            for index, item in enumerate(items):\n"
    "                if index >= len(flags) or flags[index] is not True:\n"
    "                    continue\n"
    '                if isinstance(item, dict) and item.get("filename"):\n'
    '                    proven.add((bucket, str(item["filename"])))\n'
    "    return proven\n"
    "\n"
    "\n"
    "def _video_container(filename: str) -> bool:\n"
    "    return Path(str(filename)).suffix.lower() in _VIDEO_CONTAINER_SUFFIXES\n"
    "\n"
    "\n"
    "def _video_publish_shape(\n"
    "    *,\n"
    "    bucket: str,\n"
    "    filename: str,\n"
    "    node_id: str,\n"
    "    declared_video_nodes: set[str],\n"
    "    proven_animated: set[tuple[str, str]],\n"
    ") -> bool:\n"
    '    """Does this staged entry carry the video a video terminal declared?\n'
    "\n"
    "    Only animation-bucket entries can need this: a ``videos`` bucket entry is the\n"
    "    video by itself (legacy pins).  An ``images``/``gifs`` entry counts as the\n"
    "    declared video only when the node WAS declared a video terminal, the server\n"
    "    flagged that exact entry ``animated`` (the measured 0.37 shape) and the\n"
    "    container is a video container.  Anything else stays the bucket's own kind —\n"
    "    an unproven animation-bucket entry is never the video.\n"
    '    """\n'
    "    if bucket not in _ANIMATION_BUCKETS or node_id not in declared_video_nodes:\n"
    "        return False\n"
    "    if not _video_container(filename):\n"
    "        return False\n"
    "    return (bucket, filename) in proven_animated\n"
    "\n"
    "\n"
    "def _proof_evidence(proof: dict[str, Any]) -> dict[str, Any]:\n"
    '    """JSON-able shape proof (sets → sorted ``bucket:filename`` strings)."""\n'
    "    return {\n"
    '        "declared_video_nodes": list(proof.get("declared_video_nodes") or ()),\n'
    '        "required_for": list(proof.get("required_for") or ()),\n'
    '        "source": str(proof.get("source") or ""),\n'
    '        "proven_animated": sorted(f"{bucket}:{filename}"\n'
    '                                  for bucket, filename in (proof.get("proven") or ())),\n'
    "    }"
)

# ── 5. _video_shape_proof method + _compose_record signature ────────────────

A5 = _block(
    "    def _compose_record(\n"
    "        self,\n"
    "        binding: EngineInputBinding,\n"
    "        out: Any,\n"
    "        *,\n"
    "        decoded_facts: EngineDecodedFacts | None,\n"
    "    ) -> ShotExecutionRecord:\n"
    "        contract = binding.output_contract"
)
R5 = _block(
    "    def _video_shape_proof(\n"
    "        self,\n"
    "        adapter: Any,\n"
    "        out: Any,\n"
    "        terminal_outputs: dict[str, dict[str, Any]] | None,\n"
    "    ) -> dict[str, Any]:\n"
    '        """Prove the animation flags of the entries a VIDEO terminal published.\n'
    "\n"
    "        Needed only when this attempt staged an artifact from an animation bucket\n"
    "        (``images``/``gifs``) on a node the app declared as a video terminal: such\n"
    "        an entry is the declared video only when the server flagged it ``animated``\n"
    "        (the measured 0.37 SaveVideo shape), while a ``videos`` bucket entry is the\n"
    "        video by itself (the legacy-pin shape, kept).  The flags come from this\n"
    "        prompt's own history entry — the entry the engine just validated — and a\n"
    "        read that cannot be made is refused typed instead of guessed around.\n"
    '        """\n'
    "        declared = {\n"
    '            str(node): str((conf or {}).get("kind") or "")\n'
    "            for node, conf in (terminal_outputs or {}).items()\n"
    "        }\n"
    '        declared_video_nodes = {node for node, kind in declared.items() if kind == "video"}\n'
    "        proof: dict[str, Any] = {\n"
    '            "declared_video_nodes": sorted(declared_video_nodes),\n'
    '            "required_for": [],\n'
    '            "source": "not-needed",\n'
    "            \"proven\": set(),\n"
    "        }\n"
    "        for staged in out.artifacts or ():\n"
    '            node_id = str(staged.get("node_id"))\n'
    '            bucket = str(staged.get("kind"))\n'
    "            if node_id in declared_video_nodes and bucket in _ANIMATION_BUCKETS:\n"
    '                proof["required_for"].append(\n'
    '                    {"node_id": node_id, "bucket": bucket,\n'
    '                     "filename": str(staged.get("filename") or "")}\n'
    "                )\n"
    '        if not proof["required_for"]:\n'
    "            return proof\n"
    '        prompt_id = str(out.prompt_id or "")\n'
    "        try:\n"
    "            history = adapter.transport.history(prompt_id)\n"
    "        except Exception as exc:  # noqa: BLE001 — the transport is the boundary\n"
    "            raise ComfyEngineRefusal(\n"
    "                ComfyEngineRefusalCode.ENGINE_REFUSED,\n"
    '                f"the completed attempt published {proof[\'required_for\']} in an "\n'
    '                f"animation bucket; proving the server flagged them animated needs "\n'
    '                f"this prompt\'s history entry and the read failed: "\n'
    '                f"{type(exc).__name__}:{exc}",\n'
    '                engine_code="MF_COMFY_TRANSPORT_ERROR",\n'
    "                retryable=True,\n"
    "            ) from exc\n"
    '        entry = history.get(prompt_id) if isinstance(history, dict) else None\n'
    "        entry = entry if isinstance(entry, dict) else {}\n"
    '        proof["source"] = "history"\n'
    '        proof["proven"] = _published_animation_proof(\n'
    '            entry, {str(item["node_id"]) for item in proof["required_for"]}\n'
    "        )\n"
    "        return proof\n"
    "\n"
    "    def _compose_record(\n"
    "        self,\n"
    "        binding: EngineInputBinding,\n"
    "        out: Any,\n"
    "        *,\n"
    "        decoded_facts: EngineDecodedFacts | None,\n"
    "        video_proof: dict[str, Any] | None = None,\n"
    "    ) -> ShotExecutionRecord:\n"
    "        contract = binding.output_contract\n"
    '        proof = video_proof or {}\n'
    '        proven_animated: set[tuple[str, str]] = set(proof.get("proven") or ())\n'
    '        declared_video_nodes: set[str] = set(proof.get("declared_video_nodes") or ())'
)

# ── 6. artifact classification in _compose_record ───────────────────────────

A6 = _block(
    '            app_kind = _ENGINE_KIND_TO_APP[str(staged["kind"])]\n'
    '            suffix = Path(str(staged["filename"])).suffix.lower().lstrip(".")'
)
R6 = _block(
    '            bucket = str(staged["kind"])\n'
    '            filename = str(staged["filename"])\n'
    "            app_kind = _ENGINE_KIND_TO_APP[bucket]\n"
    "            if _video_publish_shape(\n"
    '                bucket=bucket, filename=filename, node_id=str(staged.get("node_id")),\n'
    "                declared_video_nodes=declared_video_nodes,\n"
    "                proven_animated=proven_animated,\n"
    "            ):\n"
    '                app_kind = "video"\n'
    '            suffix = Path(filename).suffix.lower().lstrip(".")'
)

# ── 7. _execute: proof before composing + evidence payload ──────────────────

A7 = _block(
    "        record = self._compose_record(binding, out, decoded_facts=decoded_facts)"
)
R7 = _block(
    "        try:\n"
    "            video_proof = self._video_shape_proof(adapter, out, terminal_outputs)\n"
    "        except ComfyEngineRefusal as exc:\n"
    "            self._write_evidence(attempt_id, {\n"
    '                "status": "refused",\n'
    '                "prompt_id": out.prompt_id,\n'
    '                "counters": self._counters(adapter),\n'
    '                "refusal": exc.as_dict(),\n'
    '                "reservation": out.reservation,\n'
    "            })\n"
    "            raise\n"
    "        record = self._compose_record(\n"
    "            binding, out, decoded_facts=decoded_facts, video_proof=video_proof\n"
    "        )"
)

A8 = _block(
    '            "notes": list(out.notes),\n'
    '            "reservation": out.reservation,\n'
    '            "info": info,\n'
    "        })"
)
R8 = _block(
    '            "notes": list(out.notes),\n'
    '            "reservation": out.reservation,\n'
    '            "video_shape_proof": _proof_evidence(video_proof),\n'
    '            "info": info,\n'
    "        })"
)

EDITS: list[tuple[str, bytes, bytes]] = [
    ("docstring/measured-shape", A1, R1),
    ("terminal-maps", A2, R2),
    ("normalize-docstring", A3, R3),
    ("helpers", A4, R4),
    ("proof-method+compose-signature", A5, R5),
    ("artifact-classification", A6, R6),
    ("execute-proof-call", A7, R7),
    ("evidence-payload", A8, R8),
]


def main(argv: list[str]) -> int:
    check = "--check" in argv
    data = TARGET.read_bytes()
    print(f"target {TARGET} bytes={len(data)} crlf={data.count(bytes([13, 10]))}")
    report: list[dict] = []
    for name, anchor, replacement in EDITS:
        hits = data.count(anchor)
        report.append({"edit": name, "anchor_hits": hits,
                       "anchor_bytes": len(anchor), "replacement_bytes": len(replacement)})
        if hits != 1:
            print(f"REFUSED: {name}: anchor appears {hits} times (need exactly 1)")
            return 3
        data = data.replace(anchor, replacement, 1)
    if not check:
        TARGET.write_bytes(data)
    print(f"after  bytes={len(data)} crlf={data.count(bytes([13, 10]))} lf={data.count(bytes([10]))}")
    for row in report:
        print(f"  {row['edit']:<34} hits={row['anchor_hits']} "
              f"{row['anchor_bytes']}→{row['replacement_bytes']} B")
    print("PATCH_APPLIED" if not check else "PATCH_CHECK_ONLY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
