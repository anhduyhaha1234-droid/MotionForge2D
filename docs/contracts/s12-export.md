# S12 Export — frozen contract (S12-T01, `s12-export-v1`)

Owner: S12-T01. Consumers: T02 (capabilities/profiles), T03A (durable
run/variant/chunk + migration), T03B (chunk render/stitch/resume), T03C
(durable job/API + publication), T04A (validator), T05 (UI), T06A/B
(packaging/acceptance). No consumer may widen this contract without a new
Codex-reviewed version.

## 1. Request / response

- `POST /api/v2/projects/{project_id}/export/preflight`
  - Body: `ExportPreflightRequest` (`app/schemas/s12_export.py`):
    `video_item_id`, `profile_id`, `aspect_handling`, `checkpoint`
    (`checkpoint_id/hash/revision`), `lock` (`manifest_id/hash/generation`).
  - Response: `ExportPreflightResponse`: `contract_version`,
    `profile` (frozen dims/codec + `supported` filled by T02),
    `source_kind` (`native_4k | upscale_4k | below_4k`),
    `eligible`, `reasons[]` (closed codes), `checks[]` (per-gate detail),
    `estimate_bytes` + `estimate_basis` (heuristic, T02 refines),
    `readiness_status/policy`.
- Strict `extra="forbid"` everywhere; sha256 = lowercase 64-hex.
- **No render happens inside the HTTP request** — evaluation is pure
  (`app/services/s12_export/preflight.py:evaluate_preflight`).

## 2. Reason codes (closed)

`S12_EXPORT_OK`, `S12_EXPORT_NOT_READY`, `S12_EXPORT_SOURCE_MISSING`,
`S12_EXPORT_SOURCE_NOT_READY`, `S12_EXPORT_SOURCE_PARTIAL`,
`S12_EXPORT_LOCK_MISSING`, `S12_EXPORT_STALE_CHECKPOINT`,
`S12_EXPORT_STALE_POLICY`, `S12_EXPORT_CROSS_PROJECT`,
`S12_EXPORT_UNSUPPORTED_PROFILE`, `S12_EXPORT_ASPECT_MISMATCH`,
`S12_EXPORT_DISK_INSUFFICIENT`, `S12_EXPORT_UNKNOWN_PROJECT`,
`S12_EXPORT_UNKNOWN_VIDEO`.

HTTP mapping: unknown project/video → 404; cross-project → 409 (via
`checkpoint_cross_project` check → `S12_EXPORT_CROSS_PROJECT` reason, and
video/project mismatch → 404); stale/param → 422.

## 3. Native 4K vs upscale (Scenario F)

- Native 4K **only** when provenance says the source render is 4K **and**
  source dims are 3840x2160. File size alone never decides.
- Anything else targeting 4K is `upscale_4k` and must carry a labeled
  `upscale_method` (T02 provides the method; T01 marks it required).
- Aspect: target DAR must match source DAR within 1% or the request must use
  `letterbox`; `fail_closed` + drift → `S12_EXPORT_ASPECT_MISMATCH`. Never
  silent stretch/crop.

## 4. Checkpoint / manifest / profile contracts

- Checkpoint pin: `ApplyCheckpoint` row (`revision = 1` immutable) compared
  read-only: id present in workspace, hash equal, `reskin_config_revision`
  equal, `checkpoint.project_id == run project` (else cross-project).
- Manifest pin: `StructuralLockRepository.get_manifest` in the same workspace;
  hash equal, same video + project, generation equal, status draft/active.
  Missing → `S12_EXPORT_LOCK_MISSING`.
- Profile table (frozen dims):

  | profile_id         | WxH       | codec |
  |--------------------|-----------|-------|
  | master-4k-h264     | 3840x2160 | h264  |
  | master-4k-hevc     | 3840x2160 | hevc  |
  | preview-1080p-h264 | 1920x1080 | h264  |

  `supported` is **always false at T01** (basis string says T02 pending) —
  T02 fills real encoder-probe results, never grep-only lists.

## 5. Validation contract (T04A consumes)

`ValidationContract`: probes `resolution, codec, streams, frame_count,
frame_order, timebase, duration, av_policy, provenance, completeness`;
master 3840x2160; verdicts `PASS | FAIL | NOT_MEASURED` (insufficient
evidence → FAIL or NOT_MEASURED, never fake PASS); `.partial` suffix frozen.

## 6. Publication contract (T03C consumes)

`PublicationContract`: requires validation PASS + current readiness +
identity match + ownership fence; never overwrites completed output; `.partial`
never visible as completed.

## 7. Readiness / disk / source rules

- Readiness consumed from `compute_project_readiness` (Decision F) at
  preflight time; `ready` + current policy required. T01 does not change the
  upstream implementation.
- Disk: `shutil.disk_usage` on the managed root vs heuristic estimate
  `W*H*frames*0.5B/px` with basis string; unknown frame count → insufficient
  (fail-closed).
- Source: `VideoItem.source_artifact_id` row must exist with `state == ready`;
  `.partial` in path → `S12_EXPORT_SOURCE_PARTIAL`.
