"""Byte-precise repair of the misplaced unit-binding helpers in shot_reskin_executor.py.

The V4A patch landed five module-level helpers INSIDE `_graph_object_sha256`
(nested defs + a replaced docstring).  This repairs it by replacing the exact
region [start .. end] (anchors asserted count==1) with the intended text:
five module-level helpers, then the intact `_graph_object_sha256`.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

P = Path(
    "C:/Users/Admin/Documents/Codex/work/mf-delivery-20260929/C19/"
    "app/services/shot_reskin_executor.py"
)
NL = chr(13) + chr(10)
START = "def _graph_object_sha256(graph_obj: Mapping[str, Any]) -> str:"
END = '    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()'

BLOCK_LF = '''def _canonical_json(payload: Any) -> str:
    """Canonical JSON used by the unit-binding digest (same formula as the graph hash)."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def s10_unit_prompt_sha256(request: Mapping[str, Any]) -> str:
    """sha256 of the unit's frozen prompt text (the per-unit prompt binding)."""
    text = str((request.get("parameters") or {}).get("prompt") or "")
    if not text:
        raise ShotRenderRefusal(
            ShotRenderRefusalCode.SHOT_INPUT_MISSING,
            "the request carries no prompt text (per-unit prompt binding missing)",
        )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def s10_window_basename(chunk_id: str, span_start: int, span_end_exclusive: int) -> str:
    """Deterministic staged driving-window filename of one chunk/span."""
    safe_chunk = _SAFE.sub("_", str(chunk_id)) or "chunk"
    return f"shotwin_{safe_chunk}_{int(span_start)}_{int(span_end_exclusive)}.mp4"


def s10_unit_control(request: Mapping[str, Any]) -> dict[str, Any]:
    """The frozen CONTROL of one unit: graph + output node + seed + parameters."""
    backend = dict(request.get("backend") or {})
    graph = dict(request.get("graph") or {})
    params = dict(request.get("parameters") or {})
    return {
        "profile_id": str(backend.get("profile_id") or ""),
        "capability": str(backend.get("capability") or ""),
        "graph_file": str(graph.get("file") or backend.get("graph_file") or ""),
        "graph_file_sha256": str(
            graph.get("file_sha256") or backend.get("graph_sha256") or ""
        ),
        "output_node": str(backend.get("output_node") or ""),
        "seed": int(backend["seed"]) if backend.get("seed") is not None else None,
        "parameters": {str(k): params[k] for k in sorted(params)},
    }


def s10_unit_time_map(request: Mapping[str, Any]) -> dict[str, Any]:
    """The unit's TIME MAP: source span, fps, frame count and staged window."""
    source = dict(request.get("source") or {})
    span = dict(source.get("span") or {})
    fps = dict(source.get("fps") or {})
    out = dict(request.get("output_contract") or {})
    start = int(span.get("start_frame"))
    end = int(span.get("end_frame_exclusive"))
    return {
        "source_start_frame": start,
        "source_end_frame_exclusive": end,
        "fps_num": int(fps.get("num") or out.get("fps_num") or 30),
        "fps_den": int(fps.get("den") or out.get("fps_den") or 1),
        "frame_count": int(out.get("frame_count") or (end - start)),
        "window_basename": s10_window_basename(
            str(request.get("chunk_id") or ""), start, end
        ),
        "width": int(out.get("width") or 0),
        "height": int(out.get("height") or 0),
    }


def s10_unit_binding_digest(request: Mapping[str, Any]) -> str:
    """Digest of EVERY input a unit's render consumes, plus its unit identity.

    Callers and the engine path compute this over the SAME request dict, so a
    cached/chunk artifact may only be reused when this digest still matches the
    one recorded with the artifact: a changed prompt, anchor, cast, graph, seed,
    control, span or output shape forces a re-render.
    """
    source = dict(request.get("source") or {})
    anchor = dict(request.get("anchor") or {})
    cast: list[dict[str, Any]] = []
    for entry in sorted(
        (request.get("cast") or []),
        key=lambda e: (str(e.get("role") or ""), str(e.get("pack_version_id") or "")),
    ):
        refs = [
            {"key": str(r.get("key") or ""), "sha256": str(r.get("sha256") or "")}
            for r in (entry.get("references") or [])
        ]
        refs.sort(key=lambda r: (r["key"], r["sha256"]))
        cast.append(
            {
                "role": str(entry.get("role") or ""),
                "character_id": str(entry.get("character_id") or ""),
                "pack_version_id": str(entry.get("pack_version_id") or ""),
                "references": refs,
            }
        )
    staged = {
        str(k): {
            "relative_path": str((v or {}).get("relative_path") or ""),
            "sha256": str((v or {}).get("sha256") or ""),
        }
        for k, v in sorted((request.get("staged_inputs") or {}).items())
    }
    body = {
        "unit_id": str(request.get("unit_id") or ""),
        "shot_id": str(request.get("shot_id") or ""),
        "chunk_id": str(request.get("chunk_id") or ""),
        "prompt_sha256": s10_unit_prompt_sha256(request),
        "source": {
            "sha256": str(source.get("sha256") or ""),
            "relative_path": str(source.get("relative_path") or ""),
        },
        "time_map": s10_unit_time_map(request),
        "anchor": {
            "relative_path": str(anchor.get("relative_path") or ""),
            "sha256": str(anchor.get("sha256") or ""),
        },
        "staged": staged,
        "cast": cast,
        "control": s10_unit_control(request),
        "binding_schema": UNIT_BINDING_SCHEMA,
    }
    return hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest()


def _graph_object_sha256(graph_obj: Mapping[str, Any]) -> str:
    """The engine's own workflow hash convention (mf-comfy pinning.hash_workflow)."""
    canonical = _canonical_json(graph_obj)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
'''

with P.open(encoding="utf-8", newline="") as fh:
    text = fh.read()

if text.count(START) != 1 or text.count(END) != 1:
    print(f"ANCHOR FAIL start={text.count(START)} end={text.count(END)}")
    sys.exit(1)

i = text.index(START)
j = text.index(END) + len(END)
before, after = text[:i], text[j:]

# only the misplaced block may be removed: it must contain the nested helpers
region = text[i:j]
if region.count("def s10_unit_binding_digest") != 1 or region.count("def _canonical_json") != 1:
    print("REGION SHAPE UNEXPECTED — abort")
    sys.exit(1)

repaired = before + BLOCK_LF.replace("\n", NL) + after
with P.open("w", encoding="utf-8", newline="") as fh:
    fh.write(repaired)

data = P.read_bytes()
CRLF = (chr(13) + chr(10)).encode()
print("REPAIRED bytes=", len(data), "crlf=", data.count(CRLF), "loneLF=",
      data.count(b"\n") - data.count(CRLF))
print("module_level_defs=", len(re.findall(r"^def s10_unit_binding_digest", repaired, re.M)))
print("nested_defs_left=", len(re.findall(r"^    def s10_unit_", repaired, re.M)))
print("_canonical_json_defs=", len(re.findall(r"^def _canonical_json", repaired, re.M)))
