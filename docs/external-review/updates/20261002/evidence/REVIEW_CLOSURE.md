# Independent review closure — WAN prototype packet

2026-10-01. **PASS for the reviewed prompt and static run-local configuration correction.** No remaining blocking finding in this review scope. This closes the earlier P2 prompt finding; it does not approve a video or grant dispatch beyond the user's existing authority.

Reviewed final prompt SHA-256: `74f4889ed43f426d30216df67e98bcb9503a926a4ebe65363962736e83fcc96d`.

Reviewed REUSE_EXECUTION_MATRIX.md SHA-256: `a1ee74aa94b488d4ae72ff1ee6d2cf800035c56b0913b5ce5e7d4e78a4d287a1`.

Reviewed corrected API graph SHA-256: `7da45b824d0c0810a5ff318fcf713914fb211a6405985de9e22435a042e448c7`.

## Closed / verified

- Earlier P2 hidden-video-variant ambiguity is closed: one sampled output, no seed sweep/best-of-N/hidden alternatives, additional variants consume the existing allowance. Video batch size is correctly distinguished from temporal IMAGE batches and RebatchImages.
- Source occlusion wording now preserves the visible/hidden portions of each role. It does not require revealing an originally hidden person.
- Demo-first scope remains authorized; app/UI/public API corrections are deferred rather than placed back in front of the experiment.
- Reuse instructions require the existing native Comfy graphs and the run-local motion-enabled copy; no new inference engine, global runtime change, model shopping or broad research prerequisite was added.
- The motion-window finding is precise: zero-width 0..0 may supply driving conditioning at the initial boundary only with the inspected schedule, while the remaining steps omit that direct conditioning. It is not described as proof of zero source influence on every step. Earlier conditioning can of course affect the later generated state.
- Installed UI-template start/end wiring is identified; an unchanged re-export is prohibited. The corrected expanded API graph has exactly one JSON value delta, end 0→1, and the stated hash/provenance match.
- Old P6 performance is not advertised as a full-window performance measurement. GPU time, VRAM and quality remain to be remeasured in the authorized loop.
- The same 10-candidate ceiling, per-unit submission cap, image/vision/model budgets, shared deadline, early stop and final Codex boundary remain intact. Sequential continuation frames are not miscounted as independent best-of-N products; bounded spans and sampler passes must be logged.

## Execution checks that remain

Real vision capability, correct source/cast bindings, model/node availability, full-window memory/runtime and actual visual quality must be checked during the authorized experiment. They are not newly established failures or reasons to demand another planning round now. The static correction does not guarantee video acceptance.

The final media state remains NOT_APPROVED / NOT_CLOSED and QUALITY_ACCEPTED=0 until Codex reviews the actual submitted result. No GPU inference, runtime/source/template modification or Hermes dispatch occurred in this review. The only reviewer writes were the requested review artifacts.
