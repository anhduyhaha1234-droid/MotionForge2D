# MF-V1-BENCH — EVAL_PLAN.md (how the wave-2 video candidate will be evaluated)

Frozen inputs today are the PROPAGATE reconstruction baseline (wave-1 evidence, quarantined owner, never
re-run). This plan describes how a **new video candidate** from MF-V1-VIDEO14B is judged when it lands.

## 1. Inputs the candidate must arrive with

| input | required form | why |
|---|---|---|
| candidate clip | video file, per-window or assembled, **unchanged FPS/duration** vs the source window it claims to cover | `duration_contract`, `frame_count_exact`, `pts_contract` |
| the source clip it claims to cover | the exact window extract (`runtime/bench/src_windows/<TAG>_src.mp4`, reproducible from the film pin `5a175454…9fa2` at `t0 = start_frame/30`) | before/after pairing, `not_source_copy`, `cut_timeline` |
| mapping / padding manifest | JSON: window_id → source start_frame, frame_count, output frame count, any padding/offset applied | otherwise a shifted candidate can be mistaken for a bad render |
| audio decision | either the source audio track preserved with the same timestamps, or an explicit statement that the candidate is video-only | `audio_contract` (`NOT_APPLICABLE` needs the reason recorded) |
| engine facts | engine name/version, checkpoint hash, config (denoise/steps/seed), wall time, peak VRAM/RSS | winner selection ties break on speed/resources, not on model name |

## 2. Exact commands (one per row group)

```bash
cd C:/Users/Admin/Documents/Codex/work/mfv1/wt-bench
# machine rows for a thin slice of metadata
python experiments/mf_reskin_v1/bench/probe.py --out raw/probe_<tag>.json <candidate.mp4>
# all machine assertions + alignment facts for one window
python experiments/mf_reskin_v1/bench/run_dryrun.py --steps candidate \
  --candidate <candidate.mp4> --source-clip <src_window.mp4> --window-tag BOOK --expected-frames 120
# review pack (contact sheets, cut/grip crop strips, 1x + 0.5x copies, visual calibration inputs)
python experiments/mf_reskin_v1/bench/run_dryrun.py --steps sheets
# whole-frozen-set regression of the harness itself (unchanged expectations, kept reds)
python experiments/mf_reskin_v1/bench/run_dryrun.py --steps golden,extract,propagate,stills,negatives,sheets,report
```

Each run writes `raw/candidate_<tag>.json` (measured values, per-assertion verdicts) and appends every
ffmpeg/ffprobe call with argv/cwd/exit/duration to `raw/cmd_transcript.jsonl`.

## 3. Order of judgement

1. **Machine rows first** (row 8 + row 5 + row 7 proxies): `pts_contract`, `duration_contract`,
   `frame_count_exact`, `video_codec_contract`, `audio_contract`, `cut_timeline`, `frame_pairing`,
   `non_degenerate_frames`, `not_frozen`, `not_source_copy`. A candidate that fails any of these is reported
   as `TECHNICAL_FAIL` with the measured values; it is not silently dropped and not re-rendered to fit the gate.
2. **Rows 1–4, 6 and the semantic half of 3 and 7 are `NOT_REVIEWED`** the moment the machine rows finish.
3. **Reviewer pass.** The reviewer gets: the contact sheets, the centre crop strips at the BOOK anchors, the cut
   strip at the measured cut frame, the 1× and 0.5× copies of each window and of the assembled set, plus the two
   calibration clips in `review/vcal/` (a reviewer who passes a calibration clip is not admissible). The
   reviewer fills one row record per CHECKLIST row using the template in CHECKLIST.md.
4. **Identity/style (row 6)** is answered only from playback. No metric on this route substitutes for it.

## 4. Choosing the winner (acceptance first, then cost)

`accepted quality first, then speed / resources / manual-fix effort`:

1. a candidate with any unresolved row-1..7 FAIL or NOT_REVIEWED is not a winner, whatever its test counts;
2. among candidates that pass the reviewer's rows, prefer the one with fewer required manual fixes (hand/limb
   cleanup, mask repair) measured in touched frames;
3. then wall time per 4 s window and peak VRAM/RSS (both recorded in the run facts);
4. then cost/licence (a non-commercial licence needs explicit user acceptance);
5. green counters and model names are **not** selection criteria. A candidate that only wins on
   `not_source_copy` being "below threshold" is a reconstruction, not a reskin — that is a FAIL, not a pass.

## 5. Launch slice for wave 2

- slice A: `BOOK` 4 s (character + both hands + book grip: the interaction group that broke the previous demo);
- slice B: `CUT_660` 4 s (hard cut handling, measured cut offsets);
- slice C: `OCC_14768` 4 s (second person present, overlap/occlusion);
- then the full 7-window / 28 s set including the `W07_HOLDOUT` holdout, which is not used for tuning.
- `W05_CAMERA` carries the known degenerate source frames (f4212, f4227 are pure black); its geometry stays
  uninformative — the window is reported with that caveat and is never used to claim camera-motion quality.

## 6. If both candidates fail (the branch that must be planned for)

Hand back, without softening:

1. the measured failures per row (values + artifact paths) and which rows were never reviewable;
2. the concrete local limits that produced them: 12,227 MiB card, no VACE/Animate weights on disk, the measured
   appearance failure of SDXL img2img at every tested denoise, the source-derived appearance of the propagation
   baseline;
3. the smallest next experiments that would be informative (e.g. one 4 s window at a different resolution/step
   budget, or the same input on a larger GPU/cloud), each with its own pre-registered rule;
4. an explicit statement that no gate was widened and no row was converted to PASS to unblock the wave.
