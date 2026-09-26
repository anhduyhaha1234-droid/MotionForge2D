"""MF-V1-BENCH round D - PRE-STAGED intake gate for the first frozen I1/I2 media artifact.

This tool exists so that the moment the first frozen artifact lands, evaluation can start without
inventing anything: it REFUSES to declare a package evaluable unless the identity of the artifact is
fully proven, and it prints exactly which rows would then apply.

It never runs an evaluation row, never writes a quality verdict, never touches a threshold.

Verdicts (fail closed, first failure wins):
  INTAKE_REFUSED:ARTIFACT_ABSENT            candidate path missing / not a file
  INTAKE_REFUSED:ARTIFACT_EMPTY             candidate is 0 bytes  (pitfall #25: exit 0 + no bytes)
  INTAKE_REFUSED:HASH_MISMATCH              measured sha256 != declared sha256
  INTAKE_REFUSED:SIZE_MISMATCH              measured bytes != declared bytes
  INTAKE_REFUSED:MISSING_FIELD:<field>      a required identity/geometry/engine field is absent
  INTAKE_REFUSED:PLACEHOLDER_VALUE:<field>  a field still carries a template placeholder
  INTAKE_REFUSED:SOURCE_UNPROVEN:<reason>   source window not reproducible from the film pin
  INTAKE_READY                              identity proven; the rows below may then be run

Usage:
  python -B waveD_intake_preflight.py <manifest.json> [--json-out <path>]
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

FILM_PIN = "5a175454"  # the film pin prefix pinned by EVAL_PLAN.md; full pin lives in the frozen src windows
POSITIONS = ("video_only", "preserved")

# rows that apply to a NEW candidate, from EVAL_PLAN.md section 3, EXACTLY as written there
MACHINE_ROWS = ("pts_contract", "duration_contract", "frame_count_exact", "video_codec_contract",
                "audio_contract", "cut_timeline", "frame_pairing", "non_degenerate_frames",
                "not_frozen", "not_source_copy")
SEMANTIC_ROWS = ("row1_reference_identity", "row2_reference_motion", "row3_semantic_half",
                 "row4_reference_texture", "row6_identity_style_playback",
                 "row7_semantic_half")

REQUIRED = (
    ("artifact.path", ("artifact", "path")),
    ("artifact.sha256", ("artifact", "sha256")),
    ("artifact.bytes", ("artifact", "bytes")),
    ("artifact.window_id", ("artifact", "window_id")),
    ("source_window.path", ("source_window", "path")),
    ("source_window.film_pin", ("source_window", "film_pin")),
    ("source_window.start_frame", ("source_window", "start_frame")),
    ("mapping.frame_count", ("mapping", "frame_count")),
    ("mapping.output_frame_count", ("mapping", "output_frame_count")),
    ("audio.decision", ("audio", "decision")),
    ("engine.name", ("engine", "name")),
    ("engine.version", ("engine", "version")),
    ("engine.checkpoint_sha256", ("engine", "checkpoint_sha256")),
    ("engine.config.steps", ("engine", "config", "steps")),
    ("engine.config.seed", ("engine", "config", "seed")),
    ("engine.wall_s", ("engine", "wall_s")),
)
PLACEHOLDER_TOKENS = ("PLACEHOLDER", "TBD", "TODO", "<", "xxx", "FILL_ME")

# Pre-staged template. Deliberately left full of placeholders: feeding it to this tool MUST be
# refused (PLACEHOLDER_VALUE), which is the proof that a placeholder package cannot be mistaken
# for a real artifact and cannot produce a result that does not exist.
TEMPLATE = {
    "artifact": {"path": "<candidate.mp4>", "sha256": "PLACEHOLDER", "bytes": 0,
                 "window_id": "TBD", "fps": "PLACEHOLDER", "frames": 0,
                 "assembled": "PLACEHOLDER"},
    "source_window": {"path": "<runtime/bench/src_windows/TAG_src.mp4>",
                      "film_pin": "5a175454PLACEHOLDER", "start_frame": 0},
    "mapping": {"window_id": "TBD", "source_start_frame": 0, "frame_count": 0,
                "output_frame_count": 0, "padding_or_offset": "PLACEHOLDER"},
    "audio": {"decision": "video_only", "reason": "PLACEHOLDER"},
    "engine": {"name": "PLACEHOLDER", "version": "PLACEHOLDER",
               "checkpoint_sha256": "PLACEHOLDER",
               "config": {"steps": 0, "seed": 0, "denoise": "PLACEHOLDER"},
               "wall_s": 0, "peak_vram_mb": 0, "peak_rss_mb": 0},
    "_comment": "fill EVERY field from the run that produced the artifact; this tool refuses "
                "placeholders and never invents a value",
}


def dig(pkg: dict, path: tuple):
    cur = pkg
    for k in path:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def field_digest(path: Path) -> tuple:
    h = hashlib.sha256()
    n = 0
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
            n += len(chunk)
    return h.hexdigest(), n


def check(manifest_path: Path) -> dict:
    res = {"artifact": "d2_intake_preflight.json", "task_id": "MF-V1-BENCH", "round": "D",
           "kind": "pre_staged_intake_gate_for_first_frozen_media_artifact",
           "manifest": str(manifest_path), "verdict": None, "reason": None}
    if not manifest_path.is_file():
        res.update(verdict="INTAKE_REFUSED", reason="MISSING_FIELD:manifest_file")
        return res
    try:
        pkg = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        res.update(verdict="INTAKE_REFUSED", reason="MISSING_FIELD:manifest_json (%s)" % exc)
        return res

    for label, path in REQUIRED:
        val = dig(pkg, path)
        if val is None or (isinstance(val, str) and not val.strip()):
            res.update(verdict="INTAKE_REFUSED", reason="MISSING_FIELD:%s" % label)
            return res
        if isinstance(val, str) and any(t.lower() in val.lower() for t in PLACEHOLDER_TOKENS):
            res.update(verdict="INTAKE_REFUSED", reason="PLACEHOLDER_VALUE:%s" % label)
            return res

    cand = Path(str(dig(pkg, ("artifact", "path"))))
    if not cand.is_file():
        res.update(verdict="INTAKE_REFUSED", reason="ARTIFACT_ABSENT:%s" % cand)
        return res
    if cand.stat().st_size == 0:
        res.update(verdict="INTAKE_REFUSED", reason="ARTIFACT_EMPTY:%s" % cand)
        return res
    got_sha, got_bytes = field_digest(cand)
    want_sha = str(dig(pkg, ("artifact", "sha256"))).lower()
    if got_sha != want_sha:
        res.update(verdict="INTAKE_REFUSED", reason="HASH_MISMATCH:measured=%s declared=%s"
                   % (got_sha, want_sha))
        return res
    if int(dig(pkg, ("artifact", "bytes"))) != got_bytes:
        res.update(verdict="INTAKE_REFUSED", reason="SIZE_MISMATCH:measured=%s declared=%s"
                   % (got_bytes, dig(pkg, ("artifact", "bytes"))))
        return res

    pin = str(dig(pkg, ("source_window", "film_pin")))
    if FILM_PIN not in pin:
        res.update(verdict="INTAKE_REFUSED", reason="SOURCE_UNPROVEN:film_pin_mismatch:%s" % pin)
        return res
    if not Path(str(dig(pkg, ("source_window", "path")))).is_file():
        res.update(verdict="INTAKE_REFUSED",
                   reason="SOURCE_UNPROVEN:src_window_not_on_disk:%s"
                          % dig(pkg, ("source_window", "path")))
        return res
    decision = str(dig(pkg, ("audio", "decision")))
    if decision not in POSITIONS:
        res.update(verdict="INTAKE_REFUSED", reason="MISSING_FIELD:audio.decision_not_in_%s"
                   % (POSITIONS,))
        return res

    res.update(verdict="INTAKE_READY", reason=None,
               artifact_identity={"path": str(cand), "sha256": got_sha, "bytes": got_bytes},
               source_identity={"path": str(dig(pkg, ("source_window", "path"))),
                                "film_pin": pin,
                                "start_frame": dig(pkg, ("source_window", "start_frame"))},
               audio_decision=decision,
               rows_that_then_apply={"machine_rows": list(MACHINE_ROWS),
                                     "semantic_rows_remain_NOT_REVIEWED": list(SEMANTIC_ROWS)},
               invariants={"accepted_seconds": 0,
                           "cost_per_accepted_second": "undefined at 0 accepted seconds",
                           "thresholds": "never adjusted to obtain green",
                           "G_I_V": "reported separately; no combined score",
                           "quality_verdict_written_by_this_tool": False})
    return res


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: waveD_intake_preflight.py <manifest.json> [--json-out <path>] "
              "| --emit-template <path>")
        return 2
    if sys.argv[1] == "--emit-template":
        dest = Path(sys.argv[2])
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(TEMPLATE, indent=1), encoding="utf-8")
        print("TEMPLATE_WRITTEN=%s (placeholders on purpose - this tool refuses it until every "
              "field is filled from a real run)" % dest)
        return 0
    manifest = Path(sys.argv[1])
    out = None
    if "--json-out" in sys.argv:
        out = Path(sys.argv[sys.argv.index("--json-out") + 1])
    res = check(manifest)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(res, indent=1), encoding="utf-8")
        res["json_out"] = str(out)
    print(json.dumps({k: res[k] for k in ("verdict", "reason", "artifact_identity",
                                          "rows_that_then_apply", "json_out")
                      if k in res}, indent=1))
    return 0 if res["verdict"] == "INTAKE_READY" else 1


if __name__ == "__main__":
    sys.exit(main())
