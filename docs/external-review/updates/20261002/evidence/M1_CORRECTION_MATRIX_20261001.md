# Finite correction matrix — MF-END-10/M1-01

All rows required; no new feature scope. Product/test owner `20260928_181955_a6d89a`; Manager owns only usage/reporting evidence. Tests below are required names/behaviors, not claims of existing test completion.

| Row / proposed assertion | Expected evidence / counts | Finding |
|---|---|---|
| C01 empty_public_create_reload | Fresh QA DB; identity POST1/draft POST1; returned IDs persisted; reload; no SQL seed | retain AC1 |
| C02 pending_double_submit_identity_and_version | Hold actual response while pending; rapid/double actions; actual request count exactly1 for each mutation; no duplicate rows | F01/F06 |
| C03 committed_response_lost_blocks_retry | Real backend commit201, abort delivery; retry control/handler cannot POST again; versions1 until reconcile | F01 |
| C04 reconcile_adopts_existing | GET finds just-created draft; adopt/complete; character visible and exact draft selected; character POST1/draft POST1 | F02 |
| C05 failed_before_commit_reconcile_empty_retry | Failure before commit; GET200 empty; explicit retry once; total persisted versions1, character1 | retain AC2 |
| C06 reconcile_failed_remains_uncertain | GET fails/malformed; no mutation/recovery-as-absence, ID retained, actionable error | F01/F02 |
| C07 multiple_versions_choose_returned_or_confirmed | Two real versions; actual selected control/asset/validation uses returned or explicitly confirmed ID; never infer newest from array order; ambiguous reconciliation no automatic pick | F03 |
| C08 required_format_409_retains_input | Existing error cases retained, actual409, no input loss | retain AC2 |
| C09 modal_keyboard_both_triggers | Header/empty-state triggers; forward/backward focus stays inside; Escape/X/done returns correct trigger; narrow390/desktop no overflow | F04 |
| C10 read_search_detail_preview_publish_regression | Related existing behavior preserved with isolated public-API fixtures; list tests actually exercised, no forbidden localhost8002 spec | AC3 |
| C11 request_budget_enforced | Limiter proven without paid call: cap reached → no next outbound request including inner retry/aux/resume; actual counts and stop receipt. No supported limiter → BLOCKED_BUDGET_GUARD before worker | F05 Manager |
| C12 sealed_submission | Actual bytes/hashes/line counts, honest per-row verdict, usable commands, four-file local commit; guards0 drift; tested hash=committed hash | F06 |

Use source locations and independent probe at `runtime/adversarial.cjs` to reproduce before correction. Keep loss-after-commit separate from loss-before-commit. Count attempts as well as responses and read all versions for that character.

Order: defect repros → corrected C01–C10 browser matrix → targeted lint/typecheck + retained contract module → one build → guards/commit/report. No broad suite while a micro repro still fails. A failed gate yields one finite finding packet, not an automatic second correction loop.
