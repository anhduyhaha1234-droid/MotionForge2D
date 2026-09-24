"""MF-V1-BENCH reporting layer - the rules that keep a report from lying.

Every rule below exists because a real report in this task got it wrong (Codex R11):

  1. ARTIFACT IDENTITY IS PER-SHA.  A geometry number belongs to exactly one sha256. The raw
     render (640x368) and the cropped export it was cut down to (640x360) are DIFFERENT
     artifacts; attributing the raw's +8-row vertical defect to the cropped candidate's hash is
     a reporting error, not a measurement error.
  2. FOUR TIME SCALES, NEVER ONE.  wall (client process) / wait (adapter wait for the server) /
     server (the engine's own "Prompt executed") / load (cold model load) are four different
     measurements with four different sources. Reporting `wait` as the wall time (or the wall as
     the server time) is forbidden; each field carries its own source locator, and a field with
     no source is recorded as `None` with a reason - never filled in with a number.
  3. GENERATED != ACCEPTED SECONDS.  `generated_seconds` is what the render produced;
     `accepted_seconds` is what a reviewer accepted. With `accepted_seconds = 0` the cost per
     accepted second is UNDEFINED - the report says the word `undefined`, never a number.
  4. G / I / V ARE SEPARATE VERDICT FAMILIES.  G = deterministic generation/artifact facts
     (machine rows). I = identity (the cast/role identity proof, needs target-library pixels).
     V = visual quality (needs a viewer). A PASS in G is not an I pass and is never a V pass.
  5. SEMANTIC fail / notmeasured IS A DIFFERENT AXIS from G/I/V.  `notmeasured` is the label for
     a measurement that has no discriminating power; it is never rendered as PASS.
  6. PROVENANCE IS EXPLICIT.  For every review artifact: the sha256 it belongs to, the frames it
     actually covers, and who (if anyone) looked at it. No viewer => NOT_REVIEWED, and
     `promotes_to_visual` stays False for any technical verdict.

No function here invents a number: inputs are measured values, and `self_check()` returns the
violations it finds so a caller can fail loudly instead of publishing a soft report.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# --- vocabulary ------------------------------------------------------------ #

HARNESS_VERDICTS = ("PASS", "FAIL", "UNKNOWN", "UNMEASURED", "NOT_REVIEWED", "NOT_APPLICABLE")

#: the packet's semantic words, kept as their own axis (lower case on purpose: they are not
#: harness verdicts and must never be confused with one)
SEMANTIC_OF_VERDICT = {
    "PASS": "pass",
    "FAIL": "fail",
    # both harness spellings of "the measurement cannot decide" collapse to the packet's word:
    # UNMEASURED is the spelling this lane's harness emits, UNKNOWN is the one GATE_VOCAB.md uses
    "UNMEASURED": "notmeasured",
    "UNKNOWN": "notmeasured",        # "no discriminating power"
    "NOT_REVIEWED": "not_reviewed",  # a viewer is required and has not answered
    "NOT_APPLICABLE": "not_applicable",
}

#: verdict families. G = generation/artifact facts, I = identity, V = visual.
FAMILY_MEANING = {
    "G": "deterministic generation/artifact facts - machine rows only",
    "I": "identity - the role/cast identity proof; needs target-library pixels",
    "V": "visual quality - needs a viewer; a G pass is never a V pass",
}

#: harness rows measured by the machine => family G. Anything not named I or V below is G.
IDENTITY_ROWS = ("identity_target", "cast_identity", "role_identity")
VISUAL_ROWS = ("character_and_hands_present", "hands_attached", "book_grip", "second_person",
               "identity_consistency", "no_blur_flicker_ghosting", "action_contact_match")

UNDEFINED_COST = "undefined (accepted_seconds = 0)"


def geometry_str(width: Optional[int], height: Optional[int]) -> Optional[str]:
    return None if width is None or height is None else "%dx%d" % (int(width), int(height))


def family_of(row_key: str) -> str:
    if row_key in IDENTITY_ROWS:
        return "I"
    if row_key in VISUAL_ROWS:
        return "V"
    return "G"


# --- 1. artifact identity -------------------------------------------------- #

def identity(candidate_id: str, path: str, role: str, sha256: Optional[str],
             bytes_: Optional[int], width: Optional[int] = None, height: Optional[int] = None,
             frames: Optional[int] = None, duration_s: Optional[float] = None,
             note: str = "", supersedes: Optional[str] = None,
             declared_contract_wh: Optional[List[int]] = None) -> Dict[str, Any]:
    """One candidate, one identity record, bound to ONE sha256."""
    geom = geometry_str(width, height)
    rec = {"candidate_id": candidate_id, "path": str(path), "role": role,
           "sha256": sha256, "bytes": bytes_,
           "geometry": {"width": width, "height": height, "width_x_height": geom},
           "frames": frames, "duration_s": duration_s,
           "geometry_is_bound_to_this_sha": sha256 is not None and geom is not None,
           "geometry_statement": (None if geom is None else
                                  "geometry %s belongs to sha256 %s (%s) and to no other artifact"
                                  % (geom, sha256, role)),
           "declared_contract_wh": declared_contract_wh,
           "matches_declared_contract": (None if not declared_contract_wh or geom is None else
                                         [width, height] == list(declared_contract_wh)),
           "supersedes": supersedes, "note": note}
    return rec


def identity_table(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The identity block of a report: every candidate, plus the cross-artifact warnings."""
    by_sha = {}
    for r in records:
        by_sha.setdefault(r.get("sha256"), []).append(r.get("candidate_id"))
    dupes = {k: v for k, v in by_sha.items() if k and len(v) > 1}
    return {"rule": "a geometry statement belongs to exactly one sha256; the raw render and the "
                    "cropped export of it are different artifacts and must never share a row",
            "candidates": records, "count": len(records),
            "shas_with_several_roles": dupes,
            "distinct_shas": sorted([k for k in by_sha if k]),
            "all_geometry_bound": all(r.get("geometry_is_bound_to_this_sha") for r in records)}


# --- 2. timings ------------------------------------------------------------ #

TIME_FIELDS = ("wall_s", "wait_s", "server_s", "load_s")


def split_timings(wall_s=None, wait_s=None, server_s=None, load_s=None,
                  components: Optional[Dict[str, Any]] = None,
                  sources: Optional[Dict[str, str]] = None,
                  reasons: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Four time scales, each with its own source locator.

    A field that was not measured stays None and needs a `reasons` entry; it is never filled in
    from another field.
    """
    values = {"wall_s": wall_s, "wait_s": wait_s, "server_s": server_s, "load_s": load_s}
    sources = dict(sources or {})
    reasons = dict(reasons or {})
    out = {}
    for k in TIME_FIELDS:
        out[k] = {"value": values[k], "unit": "s", "source": sources.get(k),
                  "measured": values[k] is not None,
                  "reason": None if values[k] is not None else reasons.get(k, "not measured")}
    missing_sources = [k for k in TIME_FIELDS if values[k] is not None and not sources.get(k)]
    return {"fields": out,
            "rule": "wall / wait / server / load are four different measurements; they are never "
                    "interchanged and never collapsed into a single reported number",
            "collapsed_into_one_number": False,
            "fields_measured": [k for k in TIME_FIELDS if values[k] is not None],
            "fields_unmeasured": [k for k in TIME_FIELDS if values[k] is None],
            "fields_without_source": missing_sources,
            "sources_complete": not missing_sources,
            "components": dict(components or {}),
            "derived": {"wait_minus_load_s": (None if wait_s is None or load_s is None
                                              else round(float(wait_s) - float(load_s), 3)),
                        "wait_minus_server_s": (None if wait_s is None or server_s is None
                                                else round(float(wait_s) - float(server_s), 3)),
                        "wall_minus_total_s": None},
            "note": "derived differences are arithmetic on the measured fields above; they are not "
                    "new measurements and never replace a field"}


# --- 3. generated vs accepted seconds -------------------------------------- #

def seconds_split(generated_seconds: Optional[float], accepted_seconds: Optional[float],
                  cost_basis: str = "wall_s", wall_s: Optional[float] = None,
                  server_s: Optional[float] = None) -> Dict[str, Any]:
    """Generated seconds are what was produced; accepted seconds are what a reviewer accepted."""
    cost = UNDEFINED_COST
    arithmetic = None
    if accepted_seconds not in (None, 0):
        basis = wall_s if cost_basis == "wall_s" else server_s
        if basis is not None:
            cost = round(float(basis) / float(accepted_seconds), 6)
            arithmetic = "%s / %s accepted_s" % (basis, accepted_seconds)
    elif wall_s is not None:
        arithmetic = ("%s / 0 accepted_s is undefined - shown as arithmetic only, never as a "
                      "throughput" % wall_s)
    return {"generated_seconds": generated_seconds, "accepted_seconds": accepted_seconds,
            "cost_per_accepted_second": cost,
            "cost_undefined": accepted_seconds in (None, 0),
            "cost_basis": cost_basis, "cost_arithmetic": arithmetic,
            "rule": "generated seconds and accepted seconds are different quantities; with "
                    "accepted_seconds == 0 the cost per accepted second is 'undefined', never a "
                    "number"}


# --- 4/5. verdict families vs the semantic axis ---------------------------- #

def row_record(row_key: str, disposition: Optional[str], measured: Any = None,
               evidence: Optional[str] = None, control: Optional[str] = None,
               family: Optional[str] = None, reason: Optional[str] = None) -> Dict[str, Any]:
    fam = family or family_of(row_key)
    disp = disposition
    return {"row": row_key, "family": fam, "disposition": disp,
            "semantic": SEMANTIC_OF_VERDICT.get(disp, "notmeasured" if disp is None else disp),
            "measured": measured, "evidence": evidence, "control": control, "reason": reason,
            "is_machine_row": fam == "G", "requires_viewer": fam in ("I", "V")}


def verdict_families(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Sort rows into G / I / V and count the semantic axis WITHOUT merging the two."""
    fams = {k: [] for k in FAMILY_MEANING}
    semantic = {}
    for r in rows:
        fams.setdefault(r.get("family", "G"), []).append(r["row"])
        semantic[r["row"]] = r.get("semantic")
    counts = {k: {"rows": v, "pass": sum(1 for r in rows if r["family"] == k and r["disposition"] == "PASS"),
                  "fail": sum(1 for r in rows if r["family"] == k and r["disposition"] == "FAIL"),
                  "notmeasured": sum(1 for r in rows
                                     if r["family"] == k and r["semantic"] == "notmeasured"),
                  "not_reviewed": sum(1 for r in rows
                                      if r["family"] == k and r["disposition"] == "NOT_REVIEWED")}
              for k, v in fams.items()}
    technical_pass = counts["G"]["pass"]
    visual_pass = counts["V"]["pass"]
    identity_pass = counts["I"]["pass"]
    return {"families": counts, "rows_by_family": fams, "semantic_axis": semantic,
            "technical_pass_count": technical_pass,
            "visual_pass_count": visual_pass,
            "identity_pass_count": identity_pass,
            "derived_visual_pass_from_technical": False,
            "derived_identity_pass_from_technical": False,
            "rule": "G / I / V are separate families; a technical (G) PASS is never reported as an "
                    "identity (I) pass or a visual (V) pass, and `notmeasured` on the semantic axis "
                    "is never rendered as PASS",
            "plain_language": ("%d technical G rows can be PASS with 0 V rows reviewed; that is a "
                               "technical result, not a quality verdict"
                               % technical_pass)}


# --- 6. provenance --------------------------------------------------------- #

def provenance(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """All-frame review provenance: what frames exist, and who actually saw them."""
    out = []
    for e in entries:
        viewer = e.get("viewer")
        scope = e.get("verdict_scope", "technical")
        out.append({"artifact": e.get("artifact"), "path": e.get("path"),
                    "sha256": e.get("sha256"), "bytes": e.get("bytes"),
                    "belongs_to_candidate_sha": e.get("belongs_to_candidate_sha"),
                    "frames_covered": e.get("frames_covered"),
                    "frames_total": e.get("frames_total"),
                    "all_frames_covered": e.get("frames_covered") == "0-%d" % (e.get("frames_total", 0) - 1)
                    if e.get("frames_total") else None,
                    "viewer": viewer, "viewer_when": e.get("viewer_when"),
                    "viewed": bool(viewer), "verdict_scope": scope,
                    "promotes_to_visual": bool(viewer) and scope == "visual",
                    "state": ("REVIEWED" if viewer else "NOT_REVIEWED"),
                    "note": e.get("note", "")})
    return {"rule": "a technical PASS is never reported as a visual PASS; a review artifact with no "
                    "viewer is NOT_REVIEWED and its frames have not been seen by anyone",
            "entries": out, "count": len(out),
            "viewed_count": sum(1 for e in out if e["viewed"]),
            "unviewed_count": sum(1 for e in out if not e["viewed"]),
            "frames_seen_by_a_viewer": sorted({e["artifact"] for e in out if e["viewed"]})}


# --- self check ------------------------------------------------------------ #

def self_check(identity_block=None, timings_block=None, seconds_block=None,
               families_block=None, provenance_block=None) -> Dict[str, Any]:
    """Return every rule violation the report contains (empty list == clean)."""
    v: List[str] = []
    if identity_block:
        for r in identity_block.get("candidates", []):
            if r.get("sha256") and r.get("geometry", {}).get("width_x_height") is None:
                v.append("identity: %s has a sha but no geometry" % r.get("candidate_id"))
            if r.get("geometry", {}).get("width_x_height") and not r.get("sha256"):
                v.append("identity: %s reports geometry %s without a sha (unbound geometry)"
                         % (r.get("candidate_id"), r["geometry"]["width_x_height"]))
        if not identity_block.get("all_geometry_bound", True):
            v.append("identity: at least one geometry statement is not bound to a sha256")
    if timings_block:
        if timings_block.get("collapsed_into_one_number"):
            v.append("timings: wall/wait/server/load were collapsed into one number")
        if timings_block.get("fields_without_source"):
            v.append("timings: measured fields without a source: %s"
                     % timings_block["fields_without_source"])
    if seconds_block:
        if seconds_block.get("accepted_seconds") == 0 and seconds_block.get(
                "cost_per_accepted_second") != UNDEFINED_COST:
            v.append("seconds: accepted_seconds == 0 but cost is not 'undefined'")
    if families_block:
        for fam, c in (families_block.get("families") or {}).items():
            if fam == "V" and c.get("pass"):
                v.append("families: V family has %d PASS row(s) - a visual pass needs a viewer "
                         "and is not a harness verdict" % c["pass"])
    if provenance_block:
        for e in provenance_block.get("entries", []):
            if e.get("viewed") and not e.get("sha256"):
                v.append("provenance: %s has a viewer but no artifact sha" % e.get("artifact"))
            if not e.get("viewed") and e.get("promotes_to_visual"):
                v.append("provenance: %s promotes an unviewed artifact to visual" % e.get("artifact"))
    return {"violations": v, "clean": not v, "checked_at": None}
