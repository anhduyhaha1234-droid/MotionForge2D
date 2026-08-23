# Video Preflight/Probe Contract V1

**Status:** Proposed for S05-T01 review
**Epic:** E03 — Import and Analyze
**Sprint:** S05 — Import/analyze vertical slice
**Gate:** G2 — Import/analyze
**Depends on:** E02 exit (S04-T05 APPROVED); `docs/architecture/DURABLE_JOB_CONTRACT.md` V1.1 (approved); `docs/architecture/VIDEO_ITEM_API.md` (S03-T03); `docs/architecture/MANAGED_ARTIFACT_CONTRACT.md` V1 (S01-T03); `docs/architecture/PERSISTENCE_DOMAIN_CONTRACT.md` V1
**Owner module (future):** `app/services/video_probe.py` (probe), import service (S05-T02)
**Scope:** **Contract only.** This document defines the preflight/probe contract, the canonical probe metadata, the supported/unsupported codec/container decision table, the bounded ffprobe safety policy, the durable metadata/job semantics and the actionable error taxonomy. It adds **no runtime code, no routes, no schemas, no migrations, no persistence, no worker/handler wiring, no frontend code, no fixtures and no tests.** Implementation is owned by S05-T02+ once this contract is approved.

---

## 1. Purpose

Before any byte of a source video is copied into managed storage, the system must cheaply and safely answer: *"is this file an importable MotionForge source, and if not, exactly why not?"*

- **Preflight** is the fast, read-only accept/reject gate that runs in the request path.
- **Probe** is the canonical metadata extraction that becomes durable input for the import job (`ANALYZE_MEDIA`, S05-T02).
- **Errors** are never a bare "failed" — every failure carries a stable code, severity, location, machine-readable reason and a Vietnamese suggested action (PRD §9 Step 5 acceptance: *"Không có issue mơ hồ chỉ ghi 'failed'"*; FR-08: severity/reason/location/action).

The durable write surface for probe metadata is **exactly** the existing `video_item` columns (`duration_ms`, `width`, `height`, `fps_num`, `fps_den`, `source_artifact_id`) plus the `artifact` row the import job registers. **No new durable columns are invented** (TASK AC3; PERSISTENCE_DOMAIN_CONTRACT §4; VIDEO_ITEM_API §5).

---

## 2. Preflight vs probe boundary

| Aspect | Preflight | Probe (durable) |
|---|---|---|
| Runs where | Request path (import submission / drop-zone validation) | First step of the `ANALYZE_MEDIA` job, executed by the durable worker (S05-T02) |
| Grounding | FR-02 media ingest; SESSION_PROTOCOL §4 — no long operation synchronously in a request; MASTER_PLAN_V1 WS-03 "Import drop zone/preflight" | FR-09 jobs (persistent state, progress/cancel/retry/resume); DURABLE_JOB_CONTRACT §3 (`ANALYZE_MEDIA`) |
| Writes | **None.** Read-only: no `video_item` mutation, no artifact registration, no byte copy, no DB row, no managed file | Durable: persists canonical probe metadata + source artifact registration **in one transaction** (§6) |
| Returns | Actionable accept/reject decision + canonical probe metadata (schema-versioned, §3) for immediate UI display | Durable `job` state, published `artifact` row and populated `video_item` probe columns |
| Budget | Bounded and fast (§5); on failure returns a stable preflight error (§7) | Bounded subprocess policy (§5); failures become the Job's error envelope (§10 of DURABLE_JOB_CONTRACT) |
| Idempotency | Inherently idempotent (read-only; same input ⇒ same result); no key required | Idempotency key `ANALYZE_MEDIA:<source_sha256>:<generation>` (§6) |

**Boundary rule (AC2):** preflight **never mutates** `video_item`, never registers artifacts and never copies bytes. The `ANALYZE_MEDIA` import job is the **only** durable write path for probe metadata and the source artifact. This mirrors the approved `ingest` cutover (DURABLE_JOB_API_CUTOVER §1: `ingest` is already a durable job with a manifest carrying the resolved project root).

---

## 3. Canonical probe metadata (schema-versioned)

The probe result is a versioned JSON payload. **`schema_version` is mandatory and a reader that does not know the version fails closed** (DURABLE_JOB_CONTRACT §7.2 checkpoint rule; same convention as `input_manifest_json`/`checkpoint_json`).

### 3.1 Payload (`schema_version: 1`)

```json
{
  "schema_version": 1,
  "probe_tool": {"name": "ffprobe", "version": "<ffprobe version string>"},
  "container": {
    "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
    "format_long_name": "QuickTime / MOV",
    "file_size_bytes": 12345678,
    "duration_seconds": 12.5,
    "start_time_seconds": 0.0
  },
  "video_stream": {
    "index": 0,
    "codec_name": "h264",
    "codec_long_name": "H.264 / AVC",
    "width": 1920,
    "height": 1080,
    "r_frame_rate": {"num": 30000, "den": 1001},
    "avg_frame_rate": {"num": 30000, "den": 1001},
    "fps_nominal": 29.97,
    "fps_avg": 29.97,
    "fps_classification": "CFR",
    "duration_seconds": 12.5,
    "nb_frames": 375,
    "pix_fmt": "yuv420p"
  },
  "audio_stream": {
    "index": 1,
    "codec_name": "aac",
    "codec_long_name": "AAC (Advanced Audio Coding)",
    "channels": 2,
    "sample_rate": 48000,
    "duration_seconds": 12.5
  },
  "has_audio": true,
  "sha256": "<64-hex lowercase>",
  "file_path": "<normalized source path, display-only>"
}
```

Rules:

- `fps_classification` ∈ {`CFR`, `VFR`}: `CFR` when `avg_frame_rate == r_frame_rate` (rational equality) and `r_frame_rate` is a valid non-zero rational; `VFR` otherwise. **Both are accepted inputs** (PRD §9 Step 1 acceptance: *"Video CFR/VFR đều map về canonical timebase chính xác"*). The classification is recorded; the canonical timebase mapping itself is **S05-T03** scope (TASK AC4; MASTER_PLAN_V1 WS-03 "Canonical timebase/CFR-VFR policy").
- `audio_stream` is present only when a usable audio stream exists; `has_audio=false` otherwise (PRD §9 Step 4 / FR-07: warn when source has no audio — see `NO_AUDIO_STREAM` in §7).
- `sha256` is computed over the raw source file (streaming hash, §5.4). It is the canonical input identity used by the import idempotency key (§6).
- `file_path` is display-only metadata for the preflight response; it is **never persisted** as a managed location (PERSISTENCE_DOMAIN_CONTRACT §2: absolute paths are never persisted as managed artifact locations; MANAGED_ARTIFACT_CONTRACT §4: only normalized relative paths are accepted).
- Stream selection: the **first** video stream and the **first** audio stream are canonical, matching the current `probe_video` behavior (app/services/video_probe.py selects the first video/audio stream). Multi-stream policy is listed as a PM decision (§9-B7).

### 3.2 Mapping to the durable write surface

| Probe field | Durable `video_item` column | `VideoMetadata` field | Notes |
|---|---|---|---|
| `video_stream.width` | `width` | `width` | CHECK `width IS NULL OR width >= 0` (models.py) |
| `video_stream.height` | `height` | `height` | CHECK `height IS NULL OR height >= 0` |
| `video_stream.r_frame_rate` (nominal) | `fps_num`, `fps_den` | `fps` (float) | CHECK `fps_num/den IS NULL OR > 0`; **rational, not float** |
| `video_stream.duration_seconds` | `duration_ms` | `duration_seconds` | `duration_ms = round(duration_seconds * 1000)`; CHECK `>= 0` |
| source file sha256 + size | `source_artifact_id` (FK to the registered `artifact` row) | — | import registers the artifact; `video_item.source_artifact_id` references it (RESTRICT FK) |
| `container.format_name` | — (not a durable column) | — | recorded in probe result artifact JSON only |
| `video_stream.codec_name` | — (not a durable column) | `codec` | recorded in probe result JSON only; no codec column exists in `video_item` |
| `audio_stream.*`, `has_audio` | — (not a durable column) | `has_audio`, `audio_codec` | recorded in probe result JSON only |
| `video_stream.nb_frames` | — (not a durable column) | `total_frames` | recorded in probe result JSON only |
| `fps_classification` (CFR/VFR) | — (not a durable column) | — | recorded in probe result JSON only; consumed by S05-T03 |

**No new durable columns are invented (AC3).** The existing contract fields are the write surface (VIDEO_ITEM_API §5: probe columns are read-only at the API until S05-T02's import path writes them).

---

## 4. Supported/unsupported codec/container decision table

**Default-supported (written into this contract, cited):**

| Container | Video codec | Audio codec | Citation |
|---|---|---|---|
| MP4 (`.mp4`) | H.264 / AVC | AAC | PRD §9 Step 6 Export presets — `4K Master`: *"3840x2160, MP4 H.264 hoặc HEVC nếu hỗ trợ, AAC, high quality"*; FR-10 4K render |
| MP4 (`.mp4`) | HEVC / H.265 | AAC | PRD §9 Step 6 / FR-10 — *"H.264 hoặc HEVC nếu hỗ trợ"*; capability-grounded, not assumed (PRD §17 NVIDIA guidance: *"không giả định mọi GPU hỗ trợ giống nhau"*) |

**Probed and recorded regardless of support (both accepted):**

| Property | Decision | Citation |
|---|---|---|
| CFR | Accepted input; classified `CFR` | PRD §9 Step 1 acceptance — CFR/VFR map to canonical timebase |
| VFR | Accepted input; classified `VFR`; canonical mapping deferred to S05-T03 | PRD §9 Step 1 acceptance; MASTER_PLAN_V1 WS-03 |

**Everything else is NOT decided here.** Any other container, video codec, or audio codec (including but not limited to: MKV, MOV, AVI, WebM, WMV, ProRes, DNxHD, AV1, VP9, MPEG-2, MPEG-4 Part 2, MP3, AC-3, Opus, PCM) is **not** granted support by this contract and is listed in §9 "Decisions deferred to PM" as a blocker with the exact decision requested. No allowlist beyond MP4/H.264/HEVC/AAC is invented (AC4; TASK: "Do not invent an allowlist beyond MP4/H.264/HEVC/AAC").

Enforcement mapping: a file whose container is not MP4 → `UNSUPPORTED_CONTAINER`; a file whose video codec is not H.264/HEVC → `UNSUPPORTED_CODEC` (reused durable permanent code); a file whose audio codec is not AAC → `UNSUPPORTED_AUDIO_CODEC` (warning; acceptance policy deferred, §9-B5). A file with **no** audio stream → `NO_AUDIO_STREAM` (warning; importable — PRD §9 Step 4 warns, it does not reject).

---

## 5. ffprobe safety and timeout policy

### 5.1 Binary discovery (single authority)

ffprobe/ffmpeg binaries are resolved **only** through `app/services/ffmpeg_utils.py` (`find_ffprobe` / `find_ffmpeg`). No guessed path, no hard-coded user directory, no duplicate discovery logic anywhere (TASK: "binary discovery ONLY via `app/services/ffmpeg_utils` (never a guessed path)"; CODEBASE_STRATEGY_REVIEW: "FFmpeg probe/render/audio utilities: Keep + harden"). Discovery failure (binary missing) is **fail-closed** and maps to `PROBE_BINARY_NOT_FOUND` (§7) — never a silent fallback or a raw traceback.

### 5.2 Invocation shape

- `subprocess.run([...], capture_output=True, text=True, timeout=...)` with **list arguments only**; `shell=True` is **forbidden** (no shell interpolation of user-controlled paths).
- Flags: `-v quiet`, `-print_format json`, `-show_format`, `-show_streams` (kept from the current helper; JSON output is the only accepted stdout contract).
- The source path is passed as a single list element; paths with spaces/special characters are safe because no shell is involved.

### 5.3 Timeout values (concrete, bounded)

| Context | Timeout | Rationale |
|---|---|---|
| **Preflight** (request path) | **10 seconds** | SESSION_PROTOCOL §4 forbids long operations synchronously in a request. ffprobe on a local file normally returns in well under 1s; 10s bounds pathological cases (network drives, very large containers) without degrading the UI. This **tightens** the current `timeout=30` in `app/services/video_probe.py` for the request path. |
| **Probe step** (`ANALYZE_MEDIA`, worker) | **30 seconds** | Kept from the current helper (`timeout=30`, app/services/video_probe.py); runs in the durable worker (FR-09), not in a request, so the longer bound is acceptable and matches existing behavior. |

A timeout maps to `PROBE_TIMEOUT` (transient; retry allowed by the durable worker §6.1 of DURABLE_JOB_CONTRACT).

### 5.4 Checksum policy

- `sha256` is computed by streaming the raw source file in bounded chunks (1 MiB), never loaded whole into memory.
- Preflight computes the checksum as part of the read-only gate; the checksum is the canonical input identity for the import idempotency key (§6).
- The checksum budget is included inside the preflight bound; on budget exhaustion the preflight returns `PROBE_TIMEOUT` (the checksum is re-attempted by the import job, which owns verification, §6.3).

### 5.5 Fail-closed mapping

| Failure | Maps to (stable code, §7) |
|---|---|
| Binary not found (`FileNotFoundError` from `ffmpeg_utils`) | `PROBE_BINARY_NOT_FOUND` |
| Source file missing | `INPUT_MISSING` |
| Source file unreadable (permission/IO) | `INPUT_UNREADABLE` |
| ffprobe non-zero exit | `PROBE_NONZERO_EXIT` |
| ffprobe timeout | `PROBE_TIMEOUT` |
| stdout not valid JSON / missing streams | `PROBE_JSON_PARSE_ERROR` / `NO_VIDEO_STREAM` |
| No video stream | `NO_VIDEO_STREAM` |

No raw `RuntimeError`/traceback ever reaches the API (current `probe_video` raises bare `RuntimeError`; this contract replaces that surface with the taxonomy in §7 for the S05 implementation).

---

## 6. Durable metadata and job/import semantics

### 6.1 Preflight is read-only

Preflight runs in the request path, performs the bounded ffprobe + checksum, and returns the accept/reject decision and canonical probe metadata (§3). It **must not** mutate `video_item`, register artifacts, or copy bytes (AC2; FR-02; SESSION_PROTOCOL §4). The existing API create/update paths already forbid probe fields with 422 (VIDEO_ITEM_API §5; `tests/test_video_item_crud.py::test_create_rejects_extra_probe_fields`); this contract keeps that read-only surface until S05-T02's import path writes them.

### 6.2 Import (`ANALYZE_MEDIA`, S05-T02) — the only durable write path

The import job persists canonical probe metadata + source artifact registration **in one transaction**:

1. **Probe step** — the worker re-runs the bounded probe (§5) and produces the schema-versioned probe result (§3). This is a durable `checkpoint`/`intermediate` artifact in the job's step plan (DURABLE_JOB_CONTRACT §9.1/§9.5).
2. **Copy step** — the source bytes are copied into the managed root using the MANAGED_ARTIFACT_CONTRACT atomic-write helpers (staging file → fsync → atomic rename → `artifact` row `state=ready`), with sha256 verification (`expected_sha256` abort-before-publish on mismatch, MANAGED_ARTIFACT_CONTRACT §5).
3. **Publication transaction (state+effect coupling, DURABLE_JOB_CONTRACT §7.1)** — in **one transaction**: insert/update the `artifact` row (`kind='video'`, `state='ready'`, sha256, size, relative path) **and** the `artifact_owner` link (`purpose='source'` for the VideoItem) **and** write the `video_item` probe columns (`duration_ms`, `width`, `height`, `fps_num`, `fps_den`, `source_artifact_id`) **and** mark the step `completed`. Only after that commit may the Job transition `running → completed` (DURABLE_JOB_CONTRACT §9.2/§9.3: `completed` requires every declared final output `ready`; "Completed chỉ sau validation" FR-09).

### 6.3 Idempotency and retry reuse

- **Idempotency-key shape** (DURABLE_JOB_CONTRACT §8.1: `job_type + ":" + canonical_input_identity + ":" + input_generation`):
  `ANALYZE_MEDIA:<source_sha256>:<generation>` where `source_sha256` is the preflight-computed checksum (stable content identity, not path) and `generation` distinguishes explicit re-imports of the same bytes (`1` for the first logical import; a deliberate "re-import anyway" bumps generation).
- **Double-submit**: submitting import with an existing active or completed Job for the same `(workspace_id, idempotency_key)` returns the existing Job / `409 IDEMPOTENCY_KEY_IN_USE` (DURABLE_JOB_CONTRACT §8.1; S02-T02 partial unique index) — exactly one effect set.
- **Retry/restart reuse**: a retry of a terminal `failed`/`cancelled` import creates a **successor Job** with the same idempotency key and generation, `predecessor_job_id` set (DURABLE_JOB_CONTRACT §6.4/§8.5). On re-claim, the worker loads the last committed checkpoint (§7.2) and **re-runs only uncommitted work**; the completed probe step's checkpoint artifact is re-linked or skipped (§9.5), so **probe results are reused instead of re-probing**. A `completed` probe step whose checkpoint sha256 still matches is never re-probed (DURABLE_JOB_CONTRACT §8.4 replay-safe window).

### 6.4 Preflight/import contract for S05-T02..T05

- S05-T02 implements the `ANALYZE_MEDIA` job per §6.2/§6.3 and the probe columns write path.
- S05-T03 consumes `fps_classification` + rational fps from the probe result to build the canonical timebase (out of scope here).
- S05-T04/S05-T05 consume the preflight accept/reject and probe metadata for the Import UI.
- All S05 tests use **only temporary/synthetic fixtures** (`tmp_path` + lavfi `testsrc`/`sine`, the `create_test_video` pattern in `tests/test_integration.py`); never `output_m05` fixtures, never production data (TASK Implementation constraints; tests/test_integration.py).

---

## 7. Actionable error taxonomy

Stable `error_code` values; `UNSUPPORTED_CODEC` is **reused** from the durable contract (DURABLE_JOB_CONTRACT §6.1 permanent class). Every error carries severity, location, machine-readable reason and a **Vietnamese suggested action** (PRD §9 Step 5 acceptance; FR-08). No error is ever a bare "failed".

| `error_code` | Class (durable) | Severity | Location | Reason (machine-readable) | Suggested action (Vietnamese) |
|---|---|---|---|---|---|
| `INPUT_MISSING` | permanent (reused from DURABLE_JOB_CONTRACT §6.1) | blocker | source file path | source file does not exist | "Tệp nguồn không tồn tại hoặc đã bị di chuyển. Vui lòng chọn lại tệp video." |
| `INPUT_UNREADABLE` | permanent | blocker | source file path | permission/IO error while reading the file | "Không thể đọc tệp nguồn (thiếu quyền hoặc tệp đang bị khóa). Kiểm tra quyền truy cập và thử lại." |
| `NO_VIDEO_STREAM` | permanent | blocker | `streams` | container has no video stream | "Tệp không chứa luồng video. Tệp này có thể không phải video hợp lệ; hãy chọn tệp video khác." |
| `UNSUPPORTED_CONTAINER` | permanent | blocker | `container.format_name` | container not in the supported set (MP4 only, §4) | "Định dạng container chưa được hỗ trợ. Chỉ hỗ trợ MP4; hãy chuyển đổi tệp sang MP4 (H.264/HEVC + AAC) rồi thử lại." |
| `UNSUPPORTED_CODEC` | permanent (reused from DURABLE_JOB_CONTRACT §6.1) | blocker | `video_stream.codec_name` | video codec not H.264/HEVC | "Codec video chưa được hỗ trợ. Chỉ hỗ trợ H.264 (AVC) và HEVC (H.265); hãy chuyển đổi codec rồi thử lại." |
| `UNSUPPORTED_AUDIO_CODEC` | permanent | warning | `audio_stream.codec_name` | audio codec not AAC | "Codec âm thanh chưa được hỗ trợ (chỉ hỗ trợ AAC). Tệp vẫn có thể import; việc xử lý âm thanh gốc theo quyết định PM (§9-B5)." |
| `NO_AUDIO_STREAM` | permanent | warning | `audio_stream` | no audio stream present | "Video không có âm thanh. Vẫn import được nhưng output sẽ không có audio (PRD §9 Step 4/FR-07)." |
| `PROBE_TIMEOUT` | transient | blocker | probe step | ffprobe/checksum exceeded the bounded budget (§5.3/§5.4) | "Quá thời gian phân tích. Hãy thử lại; nếu tệp quá lớn, hãy kiểm tra định dạng hoặc tốc độ ổ đĩa." |
| `PROBE_BINARY_NOT_FOUND` | permanent | blocker | toolchain | ffprobe/ffmpeg not found by `ffmpeg_utils` | "Không tìm thấy ffprobe. Cài đặt FFmpeg (winget install Gyan.FFmpeg) hoặc đặt MOTIONFORGE_FFMPEG/MOTIONFORGE_FFPROBE rồi thử lại." |
| `PROBE_NONZERO_EXIT` | permanent | blocker | probe step | ffprobe exited non-zero | "ffprobe không đọc được tệp. Tệp có thể bị hỏng hoặc không phải video hợp lệ; hãy kiểm tra lại tệp nguồn." |
| `PROBE_JSON_PARSE_ERROR` | permanent | blocker | probe step | ffprobe stdout is not valid JSON | "Kết quả phân tích không hợp lệ. Hãy thử lại; nếu lỗi lặp lại, hãy báo lỗi hệ thống kèm tệp nguồn." |
| `CHECKSUM_MISMATCH` | permanent | blocker | artifact (import, S05-T02) | copied file sha256 != expected source sha256 | "Kiểm tra toàn vẹn tệp thất bại (checksum không khớp). Nguồn có thể bị thay đổi hoặc hỏng; hãy kiểm tra lại tệp nguồn trước khi import." |

Notes:

- Severity `blocker` ⇒ preflight rejects the file; `warning` ⇒ preflight accepts with a visible warning (or defers acceptance per §9-B5).
- `UNSUPPORTED_CODEC`, `UNSUPPORTED_CONTAINER`, `INPUT_MISSING` reuse durable permanent semantics: the import Job goes `failed` with the envelope (DURABLE_JOB_CONTRACT §6.1 permanent; no automatic retry; manual retry only per job type).
- `PROBE_TIMEOUT` is transient ⇒ the durable worker may auto-retry with bounded backoff (DURABLE_JOB_CONTRACT §6.1).
- `CHECKSUM_MISMATCH` is the placeholder for S05-T02's copy-verification step (MANAGED_ARTIFACT_CONTRACT §5 `expected_sha256` abort-before-publish); it cannot occur in preflight (preflight writes nothing).

---

## 8. Compatibility with existing contracts

- **No schema/migration required by this contract.** The `video_item` table already carries the probe columns with CHECK constraints (`duration_ms >= 0`, `width/height >= 0`, `fps_num/fps_den > 0`, `source_artifact_id` RESTRICT FK — `app/persistence/models.py`). S05-T02 will write them through the existing write path; no DDL change is introduced here (AC9; PERSISTENCE_DOMAIN_CONTRACT §7).
- **Probe columns remain read-only at the API** until S05-T02's import path writes them. Create/update still forbid them with 422 (VIDEO_ITEM_API §5; `app/api/routes/durable_videos.py`; `app/persistence/videos.py`).
- **`channels.json`, `data/`, database files and user data are never touched** by preflight or by this contract (AC9; S00-T01 baseline isolation).
- **Contract-only rule:** reading/validating this document requires no imports of `app` runtime modules; it references code paths by path only.
- **No job-type change:** `ANALYZE_MEDIA` is already approved (DURABLE_JOB_CONTRACT §3; MASTER_PLAN_V1 §7.2). This contract pins down how preflight/probe uses it (§6).

---

## 9. Decisions deferred to PM (blockers)

Every item below is an **unresolved product decision** — the required reading does not decide it, so this contract does **not** invent behavior (TASK: "list it as a blocker in the contract's 'Decisions deferred to PM' section — never invent the behavior"; AC8).

| ID | Exact decision requested | Requirement gap (what the reading does not decide) |
|---|---|---|
| B1 | **Minimum supported input container allowlist.** Is MP4 the ONLY accepted input container in Phase 1 (reject others), or may MKV/MOV/AVI/WebM be accepted with remux/transcode? | PRD §9 Step 6 / FR-10 define the **output** preset (MP4); no input container allowlist is defined anywhere in the required reading. |
| B2 | **Maximum source file size / minimum free disk.** Is there a per-file size cap or required free-disk margin at import time? | PRD §14 covers "Thiếu disk → Dừng trước job" behaviorally but gives no numeric threshold; MASTER_PLAN_V1 WS-03 lists "disk/time estimate" but not a cap. |
| B3 | **Minimum source resolution and duration.** Can a low-resolution (e.g. 320x240) or very short (e.g. <1s) clip be imported? | PRD §9 Step 1 lists probe fields but no minimum resolution/duration acceptance. |
| B4 | **ProRes/DNxHD/intermediate-codec acceptance.** Are professional intermediate codecs accepted as import sources (they are common production inputs)? | PRD §17 research discusses capability guidance but never names ProRes/DNxHD input support. |
| B5 | **Non-AAC audio codec acceptance.** When video is H.264/HEVC but audio is MP3/AC-3/Opus/PCM: import with warning + remux/transcode fallback (FR-07), or reject at preflight? | FR-07 says preserve/remux original audio with fallback, but the accepted input audio-codec set is not enumerated; S11-T01 owns the original-audio remux contract. |
| B6 | **Unsupported video codec transcode-on-import.** For AV1/VP9/MPEG-2/... sources: transcode on import, or reject? | PRD names H.264/HEVC only in output presets; no input transcode policy exists. |
| B7 | **Multi-stream selection.** With multiple video/audio streams, is "first video stream + first audio stream" canonical (current `probe_video` behavior), or should the user/PM choose? | PRD does not define multi-stream selection; current behavior picks the first stream (evidence in `app/services/video_probe.py`). |
| B8 | **HDR/10-bit sources.** Are HEVC 10-bit / PQ / HLG sources accepted and how is tone-mapping handled? | The 4K Master preset (PRD §9 Step 6) is SDR-oriented; no HDR input decision exists. |

These blockers are also reported in `docs/pm/sessions/S05-T01-video-preflight/REPORT.md`. No contract assertion depends on resolving them; the supported set remains exactly MP4/H.264/HEVC/AAC until PM decides otherwise.

---

## 10. Acceptance invariants (provable by S05-T02+ tests)

1. Preflight is read-only: after a preflight call, `video_item`, `artifact`, `job` tables and managed files are unchanged.
2. Preflight returns either an accept (with schema-versioned probe metadata §3) or a reject (with exactly one stable error code from §7) — never a bare "failed".
3. The supported/unsupported table contains exactly MP4 + H.264 + HEVC + AAC as default-supported and CFR/VFR as both-accepted; every other format is a §9 blocker, not an invented allowlist.
4. The probe metadata mapping (§3.2) touches only existing `video_item` columns and `VideoMetadata`; no new durable columns.
5. Import persists probe metadata + source artifact registration in **one transaction**; `video_item.source_artifact_id` points at a `ready` artifact; `completed` never precedes publication/validation.
6. Double-submit of the same `ANALYZE_MEDIA:<sha256>:<generation>` creates one Job and one effect set; retry/restart reuses the checkpointed probe result instead of re-probing.
7. Every ffprobe invocation is list-args, `-v quiet`, JSON output, binary via `ffmpeg_utils`, with the §5.3 timeouts; every failure maps to a stable code.
8. The full seven-gate quality baseline remains PASS for every S05 task (QUALITY_BASELINE.md; TASK AC10).

---

## 9-R. Resolutions (append-only)

> This section only ever APPENDS resolutions; the §1–§10 text above is never rewritten.

### Resolution R-B5 — Non-AAC audio codec acceptance (S11-T01A, 2026-08-21)

**Resolves:** B5 ("Non-AAC audio codec acceptance") — the ONLY §9 decision S11 supersedes.

**Decision:** When the container is MP4 and the video codec is H.264/HEVC, a source whose **first audio stream is not AAC** is **ACCEPTED at import with an explicit warning** (`UNSUPPORTED_AUDIO_CODEC`, severity `warning`) — it is no longer rejected fail-closed. The S11 remux engine (`ATTACH_ORIGINAL_AUDIO`, `docs/architecture/ORIGINAL_AUDIO_REMUX_CONTRACT.md`) owns the transcode-to-AAC downstream. A source with no audio stream remains accepted with `NO_AUDIO_STREAM` (explicit no-audio metadata, never fabricated audio). The container / video-codec / HDR gates are unchanged and remain fail-closed.

**Implementation evidence:** `app/services/video_import.py` probe phase appends the `UNSUPPORTED_AUDIO_CODEC` warning instead of raising; regressions in `tests/test_s11_original_audio_contract.py` and `tests/test_video_import.py`.

All other §9 items (B1–B4, B6–B8) remain unresolved by this document and are NOT touched by S11.
