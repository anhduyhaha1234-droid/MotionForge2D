# MF-V1-BENCH — GATE_VOCAB.md (disposition vocabulary and recording rules)

## 1. Verdict vocabulary (exactly these five)

| verdict | meaning | who may write it |
|---|---|---|
| `PASS` | the row's rule was met by a **non-empty measurement**, or a viewer answered the row affirmatively | harness (MEASURED rows) / reviewer (VISUAL rows) |
| `FAIL` | the measurement or the viewer contradicts the row's rule | harness / reviewer |
| `UNKNOWN` | the input is present but the measurement is **empty or non-discriminating** (0 frames, `null`, flat curve) | harness |
| `NOT_REVIEWED` | the row needs a viewer and no viewer has answered | harness (always) |
| `NOT_APPLICABLE` | the row genuinely does not apply (e.g. audio row on a deliverable with no audio track); the reason must be recorded | harness |

`APPROVED`, `CLOSED` and `QUALITY_ACCEPTED` are **not** harness vocabulary. Only the Codex gate writes
`APPROVED` / `CHANGES_REQUESTED`, and only after a human/vision review answered the `VISUAL_*` rows.

## 2. The three separations this harness enforces

- `TECHNICAL_PASS` — deterministic properties (frame count, PTS contract, duration/CFR, codec, cut offsets,
  audio stream and offset) verified by measurement. Machine-only.
- `VISUAL_NOT_REVIEWED` — semantic rows (character/hands present, hands attached, grip, occlusion, identity,
  blur/flicker/ghosting) with no viewer yet. The default state of rows 1–4, 6 and the semantic half of 3 and 7.
- `QUALITY_ACCEPTED` — **requires a viewer.** A `TECHNICAL_PASS` on every machine row is not, and can never be
  promoted into, a quality verdict. The harness never writes it.

## 3. Hard rules (learned from measured failures, not from theory)

1. **Empty measurement is never PASS (F02).** The previous wave's contact gate returned `PASS` while all role
   support was deleted: `frames_measured = 0` for all 5 pairs and 5 pairs called `occluded`. If the input is
   visibly present and the measurement is empty, the row is `UNKNOWN` or `FAIL`.
2. **A metric on a copy of the source is at most a diagnostic.** PSNR against the source, texture entropy,
   unique-colour counts and LUT/palette distance can never be a semantic-quality pass. They may appear in the
   report labelled `diagnostic_only`; they cannot close a row.
3. **An assertion without a failing negative control is not evidence.** Every machine assertion in `assertions.py`
   names the deliberately broken input that must make it FAIL, and `raw/negative_controls.json` records the
   measured verdict on that broken input. `UNMEASURED` on the broken input does **not** count as proof.
4. **A test with no discriminating power reports `UNKNOWN`, not `PASS`.** Measured case: a candidate that is
   within ~1 grey level of the source makes the whole-clip |delta|-vs-offset curve flat, so frame correspondence
   cannot be localised. That is `UNKNOWN` (with the curve and the source's per-frame motion recorded), even though
   the numbers "look good".
5. **A drop that a CFR container pads away is still a drop.** A dropped frame range is re-inserted as duplicated
   frames by the 30 fps pipeline: it shows up in `pts_contract` (PTS gap) and `not_frozen` (identical run), and it
   does **not** move a cut. `DROP_RANGE` is therefore a valid control for those two rows and an invalid control
   for `cut_timeline` (control changed after measuring this).
6. **Nothing is re-tuned to make an old artifact pass.** A red row on a frozen artifact stays red in the report.
7. **No cross-owner metric is reused as truth.** If a shape/liveness idea comes from another task's harness (e.g.
   PROPAGATE `measure.py`), it must be re-derived here with its own negative control, and the report must say so.
