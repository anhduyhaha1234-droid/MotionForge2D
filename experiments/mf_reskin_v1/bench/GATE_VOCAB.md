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

## 4. Reporting rules (correction round C, Codex R11) - enforced in `reporting.py`

These are not style preferences: every one of them was a real reporting defect.

1. **Artifact identity is per-sha256.** A geometry statement belongs to exactly one artifact.
   The raw render is **640x368** (121 f) and the cropped export of it is **640x360** (120 f);
   attributing the raw's +8-row vertical defect (+2.2222 %) to the cropped candidate's hash is a
   reporting error. `reporting.identity()` prints the sha next to every geometry number and
   `identity_table()` refuses an unbound geometry.
2. **Four time scales, never one.** `wall_s` (client process) / `wait_s` (adapter wait for the
   server) / `server_s` (the engine's own "Prompt executed") / `load_s` (cold model load) are
   four different measurements. Each carries its own source locator; a field that was not
   measured stays `None` with a reason and is never filled in from another field.
3. **Generated seconds are not accepted seconds.** `generated_seconds` is what the render
   produced; `accepted_seconds` is what a reviewer accepted. With `accepted_seconds = 0` the cost
   per accepted second is **`undefined (accepted_seconds = 0)`** - the report says the word, never
   a number, and any arithmetic shown is labelled arithmetic only.
4. **G / I / V are separate verdict families.** `G` = deterministic generation/artifact facts
   (machine rows) · `I` = identity (needs target-library pixels) · `V` = visual quality (needs a
   viewer). A `G` PASS is never an `I` pass and never a `V` pass.
5. **The semantic axis is separate from the families**: `pass` / `fail` / `notmeasured` /
   `not_reviewed` / `not_applicable`. Both harness spellings of "the measurement cannot decide"
   (`UNMEASURED` and `UNKNOWN`) map to **`notmeasured`**. It is never rendered as PASS, and it is
   never rendered as a failure either: the derived verdict is
   `TECHNICAL_PASS` (all PASS/NOT_APPLICABLE), `TECHNICAL_FAIL` (at least one FAIL) or
   `TECHNICAL_NOTMEASURED` (no FAIL, at least one `notmeasured`) - measured, not asserted.
6. **Provenance is explicit.** Every review artifact records the sha256 it belongs to, the frames
   it covers and who (if anyone) looked at it. No viewer => `NOT_REVIEWED` and
   `promotes_to_visual` stays False: a technical PASS is never reported as a visual PASS.

`QUALITY_ACCEPTED` remains **0** until a viewer answers the visual rows.
