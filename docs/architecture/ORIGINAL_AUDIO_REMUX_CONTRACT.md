# Original Audio Remux Contract V1

**Status:** ACTIVE (S11-T01A)
**Epic:** E11 — Original Audio & Acceptance
**Sprint:** S11 — Original Audio & Acceptance (T01 slice)
**Depends on:** `docs/architecture/VIDEO_PREFLIGHT_CONTRACT.md` V1 (B5 resolution appended by S11-T01A); `docs/architecture/MANAGED_ARTIFACT_CONTRACT.md` V1; `docs/architecture/DURABLE_JOB_CONTRACT.md` V1.1
**Owner module:** import policy in `app/services/video_import.py` (this task, S11-T01A); remux engine + `ATTACH_ORIGINAL_AUDIO` job wiring are S11-T01B/T01C scope and read this document as their input contract.
**Supersedes:** exactly one decision of VIDEO_PREFLIGHT_CONTRACT §9 — **B5 (non-AAC audio codec acceptance)**. No other B-item, no S05/E03 history is rewritten.

---

## 1. Purpose

Freeze the product policy for the **canonical original audio** of an imported source video, so that:

- import never rejects a source **only because its first audio stream is not AAC**;
- the original audio survives to render time without silent re-encoding decisions buried in a pipeline step;
- the S11 remux engine has one authoritative statement of what it must produce.

This contract is the frozen decision record for SPRINT S11 items 3–5 of the parent prompt §8: AAC stream-copy when safe, non-AAC transcode-to-AAC at attach time, no-audio explicit metadata with no fabricated audio.

---

## 2. Canonical audio selection

| Rule | Decision |
|---|---|
| Canonical stream | The **first** audio stream of the container (`streams` order as reported by ffprobe) |
| Multi-stream inputs | Never merged. Streams other than the first audio stream are ignored by the audio pipeline; no mixing/downmixing of multiple audio streams happens anywhere in S11 |
| Selection evidence | `probe.audio_stream.index` records the ffprobe stream index of the canonical first audio stream; consumers must use this index, not "any audio stream" |

This matches VIDEO_PREFLIGHT_CONTRACT §3.1 stream-selection rule ("first video stream and first audio stream are canonical") and keeps B7 (multi-stream user choice) untouched — S11 does not reopen it.

---

## 3. Import acceptance policy (implemented in `app/services/video_import.py`)

| First audio stream | Import decision | Probe surface |
|---|---|---|
| AAC | Accept, no warning | `audio_stream.codec_name == "aac"`, no audio warning entry |
| Non-AAC (MP3, AC-3, Opus, PCM, …) | **Accept WITH explicit warning** — never reject | warning entry `code=UNSUPPORTED_AUDIO_CODEC`, `severity=warning`, `location=audio_stream.codec_name`, details carrying `audio_codec`, `audio_stream_index`, `channels`, `sample_rate` |
| Absent | Accept with existing `NO_AUDIO_STREAM` warning | `has_audio=false`; explicit no-audio metadata — **no fabricated/synthesized audio track is ever generated** |

Unchanged fail-closed gates (S11 does NOT loosen them):

- Container not MP4 → `UNSUPPORTED_CONTAINER` (reject).
- Video codec not H.264/HEVC → `UNSUPPORTED_CODEC` (reject).
- HDR/10-bit → `HDR_UNSUPPORTED` (reject).
- Non-positive duration/width/height or invalid fps rational → `INVALID_VIDEO_METADATA` (reject).

The stable code `UNSUPPORTED_AUDIO_CODEC` is **reused but demoted**: severity moves from blocker (V1 preflight placeholder) to warning per the B5 resolution appended to VIDEO_PREFLIGHT_CONTRACT §9. Its Vietnamese suggested action text stays the canonical user-facing guidance.

---

## 4. Remux / transcode policy (binding for S11-T01B)

The ATTACH_ORIGINAL_AUDIO path (T01B engine, T01C job wiring) must:

1. **AAC first audio → stream-copy when safe.** `-c:a copy` inside an MP4-compatible remux; no re-encode. If stream-copy is unsafe (e.g. codec-in-container mismatch), fall back to transcode and record which path was taken.
2. **Non-AAC first audio → transcode to AAC.** One deterministic encode profile owned by T01B; the source file itself is never mutated.
3. **No audio → explicit NO_AUDIO_PRESENT outcome.** No silent track injection, no synthesized tone.
4. **Fail closed on corrupt/unreadable audio** — no silent fallback to a different stream or to fabricated audio.
5. Source bytes remain read-only end-to-end: analysis generation and published source artifacts are unchanged by any remux operation.

Import itself performs **no transcode and no remux**: the ANALYZE_MEDIA job copies source bytes verbatim (checksummed). Remux/transcode happens only downstream in the ATTACH_ORIGINAL_AUDIO job.

---

## 5. Scope boundaries

- No Demucs/ASR/TTS/dubbing/QC/final-render UI/frontend work in S11-T01.
- No schema/migration: audio policy state lives in probe JSON (checkpoint/artifact JSON), not new durable columns.
- History of S05/E03 documents is preserved verbatim; the single B5 resolution is recorded append-only in VIDEO_PREFLIGHT_CONTRACT §9.
