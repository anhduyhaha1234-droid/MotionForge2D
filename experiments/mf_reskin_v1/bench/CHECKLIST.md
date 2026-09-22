# MF-V1-BENCH — CHECKLIST.md (finite acceptance checklist)

This is the **whole** list: 8 rows. It is not inflated per render, and a row is added only by a Codex/PM
decision — never by the harness owner while evaluating a candidate.

Vocabulary and recording rules: `GATE_VOCAB.md`. A row is recorded with a verdict in
`PASS / FAIL / UNKNOWN / NOT_REVIEWED / NOT_APPLICABLE`, the **measured value**, the artifact path and the
command that produced it, and the **negative control that must fail**. An assertion without a failing
negative control is not evidence.

`kind`: `MEASURED` = machine, deterministic · `VISUAL` = needs a viewer (human or vision-capable reviewer) ·
`HYBRID` = machine proxy plus a viewer semantic judgement (both are recorded, the proxy never upgrades the row).

| # | item | kind | exact measurement | pass rule | tool / command | negative control that must fail | wave-2 evidence |
|---|---|---|---|---|---|---|---|
| 1 | character present and both hands present in the expected frames | VISUAL | `sheet.py` contact sheet + centre crop strip at every anchor frame of the window (BOOK anchors = f1650/1665/1680/1695/1710/1725/1740/1755) | a viewer sees the character AND both hands in every anchor crop | `run_dryrun.py --steps sheets` → `crops/BOOK_grip_after_centre_320x180.png`, `sheets/BOOK_after_1fps_4x4.png` | `review/vcal/VCAL_hands_region_removed_BOOK_after.mp4` — the reviewer must call rows 1–2 FAIL on it | the crop strip + the reviewer's row-1 answer |
| 2 | hands attached to the body (no detached/floating hand, no duplicated hand) | VISUAL | same crops, watched as playback (1× and 0.5×) | no detached, floating or duplicated hand at any anchor or between anchors | `review/BOOK_after_1x.mp4`, `review/BOOK_after_0p5x.mp4` | `review/vcal/VCAL_hands_region_removed_BOOK_after.mp4` | reviewer answer + the two review copies |
| 3 | book grip maintained at the expected interaction timing | HYBRID | timing: frame correspondence to the source window around the grip anchors (`frame_pairing`); semantics: the grip itself | machine: `frame_pairing` min at offset 0 with margin ≥ `pairing_margin_floor`; viewer: grip visibly held through the anchor frames | `run_dryrun.py --steps candidate --candidate <out.mp4> --source-clip <src_window.mp4> --window-tag BOOK` | `SHIFT_3` (content shifted 3 frames) — timing row must FAIL | `raw/candidate_BOOK.json` + reviewer answer on the grip crops |
| 4 | second person still present and not occluded/lost | VISUAL | full-frame contact sheet for the overlap/occlusion window (OCC_14768) at 1× and 0.5× | the second person is visible and not lost/duplicated at any frame | `--steps sheets` → `sheets/OCC_14768_after_1fps_4x4.png`, `review/PROPAGATE_assembled_28s_1x.mp4` | a reviewer who defends this row must reject any candidate where the second role is missing — no machine control exists, so the row cannot be closed by the harness | reviewer answer |
| 5 | props and background actually changed (a source copy must FAIL this row) | MEASURED | per-frame median absolute difference vs the source window, grey levels 0–255: `compare.delta_facts` | `mae_median >= 2.0` (a visible change), **and** the source copy scores 0.0 → FAIL | `run_dryrun.py --steps candidate ...` → `not_source_copy` | `SOURCE_COPY` (byte copy of the source window) — measured FAIL, control proven in `raw/negative_controls.json` | `raw/candidate_*.json` → assertion `not_source_copy` |
| 6 | identity/style consistency across the clip (no identity flip) | VISUAL | contact sheet + 1×/0.5× playback; the harness supplies no identity metric | a viewer sees one stable identity/style for the whole clip | `--steps sheets`; no metric exists on this route | a reviewer who defends this row must reject the `SOURCE_COPY` calibration clip's *unchanged* identity as a reskin proof | reviewer answer |
| 7 | no abnormal blur / flicker / ghosting at cuts and at fast motion | HYBRID | proxy: `non_degenerate_frames` (per-frame std), `not_frozen` (identical-run length), `cut_timeline` (extra/missing cut offsets); semantic: the cut crop strip | proxy rows PASS **and** the viewer sees no blur/flicker/ghosting in `crops/CUT_660_cut_after_centre_320x180.png` (frames cut−15…cut+15) | `--steps sheets`; `raw/candidate_*.json` | `BLACK_TAIL`, `FREEZE_TAIL`, `SHIFT_3` (each measured FAIL in `raw/negative_controls.json`) | proxy verdicts + reviewer answer |
| 8 | cut positions, motion phase and audio events on the correct timeline versus source | MEASURED | `pts_contract` (pts = frame_id·512, tb 1/15360, t = frame_id/30), `duration_contract` (30/1 CFR), `frame_count_exact`, `cut_timeline`, `audio_contract`, plus audio-offset measurement | every machine row PASS or explicitly NOT_APPLICABLE; no UNMEASURED row may be reported as PASS | `probe.py`, `compare.py`, `--steps candidate` | `DROP_RANGE` (PTS gap), `FPS_25`, `TAIL_TRUNCATE`, `DOWNSCALE`, `NO_AUDIO`, `SHIFT_3` | `raw/candidate_*.json` + `raw/negative_controls.json` |

## Recording a row

```
row <n> | kind=MEASURED|VISUAL|HYBRID | verdict=PASS|FAIL|UNKNOWN|NOT_REVIEWED|NOT_APPLICABLE
  measured: <value> (<unit>)            # e.g. mae_median 1.18 grey levels, 120 frames, pts 0..60928 step 512
  evidence: <artifact path>             # raw json / png / mp4 that a third party can open
  command:  <argv that produced it>
  control:  <the broken input that makes this row FAIL, and the measured result on it>
  reviewer: <who answered, when>        # VISUAL/HYBRID rows only; empty => NOT_REVIEWED
```

## The rule that keeps this honest (F02 lesson)

A row whose input is **visibly present** but whose **measurement is empty** (0 frames measured, `null` distance,
no samples) is `UNKNOWN` or `FAIL` — **never `PASS`**. The previous wave's contact gate reported PASS while every
role support had been deleted and 0 frames were measured; that is exactly the failure this checklist forbids.
`NOT_APPLICABLE` is only for a row that genuinely does not apply (e.g. audio when the deliverable has no audio
track), and it still requires the reason to be recorded.

## What the harness can never close on this route

Rows 1, 2, 4, 6 and the semantic half of rows 3 and 7 need eyes. The harness (CPU, no vision) must mark them
`NOT_REVIEWED` and hand over the crops, strips and 1×/0.5× copies. `QUALITY_ACCEPTED` is not a harness verdict.
