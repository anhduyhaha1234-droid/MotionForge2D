# Canonical Timebase & Proxy Artifact Contract

Reference: S05-T03 implementation (`app/services/timebase.py`, `app/services/video_proxy.py`).

## 1. CanonicalTimebase

A frozen dataclass that defines one deterministic timeline mapping using **exact rational arithmetic** (`fractions.Fraction`) — never binary-float drift.

### Construction

| Constructor | Source of truth |
|---|---|
| `from_rational(num, den, ...)` | Explicit integer numerator/denominator |
| `from_probe(probe_dict)` | S05-T02 canonical probe payload |

**Classification** is `CFR` or `VFR`.  CFR uses `video_stream.r_frame_rate`; VFR uses `video_stream.avg_frame_rate`.  Both rationals must be positive — a zero/negative/invalid rational fails closed with `INVALID_TIMEBASE`.

**Duration** is optional; when provided it is normalized to an exact `Fraction` via `exact_seconds()`.  `nb_frames` is optional; when absent/zero it is derived from `round_half_up(duration × fps)` with a minimum of 1 for any positive duration.

### Exact conversions

| Method | Semantics |
|---|---|
| `frame_to_time(frame)` | Exact `Fraction`: `frame × fps_den / fps_num`.  Raises `INVALID_FRAME_INDEX` for negative frame. |
| `time_to_frame(time, rounding=)` | Floor / round_half_up / ceil.  All three are monotonic non-decreasing in the timestamp. |
| `nearest_frame(time)` | Alias for `time_to_frame(..., rounding="round_half_up")`. |
| `clamp_frame(frame)` | Clamps into `[0, nb_frames - 1]` (playhead semantics). |
| `frame_count_for_duration(d)` | Nearest-half-up `round(d × fps)`, min 1 for positive d; 0 for zero; `INVALID_DURATION` for negative. |
| `duration_for_frames(n)` | Exact `n × fps_den / fps_num`.  `INVALID_FRAME_INDEX` for negative n. |

### Monotonicity

- Increasing frames → strictly increasing exact times.
- Increasing timestamps → non-decreasing frame indices (floor/round_half_up).

### Serialization

```python
tb.to_json()  # → dict with schema_version=1, fps_num, fps_den, classification, optional duration_seconds, nb_frames
CanonicalTimebase.from_json(payload)  # → rebuild; unknown schema version fails closed
```

Rationals are serialized as `str(Fraction)` to preserve exact values.  The `GENERATE_PROXY` job persists this payload in its checkpoint so a restarted job resumes the exact same canonical grid.

## 2. Proxy Generation Pipeline

Five phases, one durable sync step (`PROXY_STEP_CODE = "proxy"`):

```
submit → source → timebase → generate → verify → publish
```

| Phase | Responsibility |
|---|---|
| **Source** | Re-validates ownership + source artifact at run time; resolves the managed source file read-only; runs bounded probe (30 s, list-args, JSON); checkpoints probe evidence (absolute `file_path` stripped). |
| **Timebase** | Builds `CanonicalTimebase.from_probe(probe)`; persists schema-versioned payload in checkpoint. |
| **Generate** | Runs FFmpeg with list arguments only (no shell), discovery only via `ffmpeg_utils.find_ffmpeg`, bounded by `ProxyProfile.timeout_seconds`.  Polled against `ctx.is_cancelled()`: cancel terminates + removes staging partial. |
| **Verify** | Bounded-probes the generated proxy: must decode (positive duration/width/height), fps must equal canonical grid exactly, duration must match source within tolerance ratio (5%, floored at 0.05 s). |
| **Publish** | Atomically moves staged file → final managed path; upserts `artifact` row (`kind=video`, `state=ready`, sha256, size, relative path) + `artifact_owner` link (`purpose=proxy`) in ONE transaction.  DB failure removes only files created by this attempt. |

Every phase is resumable: checkpointed evidence is reused when the managed file still matches (no redundant re-probes or re-encodes).

## 3. Idempotency

**Owner-scoped key shape:**

```
GENERATE_PROXY:video_item:<video_item_id>:<source_sha256>:<generation>
```

- Same source bytes into two VideoItems → two independent Jobs / effect sets.
- `completed` duplicate → same Job reused (`reused=True`).
- Active duplicate → `IdempotencyKeyInUse`.
- Retry/restart of a failed/cancelled Job → successor with same key + generation.

## 4. Stable Error Codes

| Code | Module | Meaning |
|---|---|---|
| `INVALID_TIMEBASE` | timebase | Frame-rate rational must be positive |
| `UNSUPPORTED_CLASSIFICATION` | timebase | Classification must be CFR or VFR |
| `INVALID_FRAME_INDEX` | timebase | Frame index must be non-negative |
| `INVALID_DURATION` | timebase | Duration must be non-negative |
| `SOURCE_ARTIFACT_NOT_FOUND` | video_proxy | Source artifact not in workspace |
| `SOURCE_NOT_READY` | video_proxy | Source not a ready video with checksum |
| `SOURCE_OWNER_MISMATCH` | video_proxy | Source not linked as source of VideoItem |
| `SOURCE_FILE_MISSING` | video_proxy | Managed source file missing or size mismatch |
| `FFMPEG_BINARY_NOT_FOUND` | video_proxy | ffmpeg not discoverable |
| `PROXY_FFMPEG_FAILED` | video_proxy | ffmpeg exited non-zero |
| `PROXY_TIMEOUT` | video_proxy | FFmpeg exceeded bounded budget (transient) |
| `PROXY_VALIDATION_FAILED` | video_proxy | Proxy metadata not truthful |
| `INVALID_PROXY_PROFILE` | video_proxy | Profile knobs out of bounds |
| `PATH_CONTAINMENT` | video_proxy | Managed path escape detected |

Every code carries a Vietnamese suggested action (`VIETNAMESE_ACTIONS`).

## 5. Path Containment

- Every managed path goes through `ManagedRoot`.  `ManagedPathError` maps to `PATH_CONTAINMENT`.
- **No absolute managed path is ever persisted.**  Checkpoints and manifests carry only normalized relative paths.  The probe payload's display-only `file_path` is stripped before durable storage.
- Staging: `staging/<job_id>/<step_code>/proxy.mp4`
- Final: `artifacts/<workspace_id>/video/<job_id>/<step_code>/proxy.mp4`

## 6. Schema

**No new schema.**  The durable write surface is exactly the existing `artifact` and `artifact_owner` tables.  The canonical timebase and proxy profile are persisted only in the Job checkpoint/attempt JSON.

## 7. Output Validator

`GENERATE_PROXY` registers an `output_validator` that re-verifies the published file on disk (exists + sha256 + size match the handler's evidence).  A Job can never reach `completed` before verified publication.
