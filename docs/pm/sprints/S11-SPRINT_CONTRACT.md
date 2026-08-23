# S11 SPRINT CONTRACT — Original Audio & Acceptance

**Status:** IN_PROGRESS — T01 slice active
**Authority:** CODEX/BA verdict SAFE_TO_PARALLELIZE_WITH_EVIDENCE (S11-T01 only, depends on E03 APPROVED)
**Worktree:** C:\Users\Admin\MotionForge2D-worktrees\s08-integration (branch codex/s08-integration @ a43b20da742996bafcb2f9d1ac57b10d3f1a5204)

## Task map

| Task | Tên | State | Ghi chú |
|---|---|---|---|
| S11-T01A | Audio Import Policy and Contract | READY (Wave 1) | owning session riêng |
| S11-T01B | Original Audio Remux Engine | READY (Wave 1) | owning session riêng |
| S11-T01C | Durable ATTACH_ORIGINAL_AUDIO Job Wiring | BLOCKED_ON_T01B | dispatch khi T01B MANAGER_VERIFIED |
| S11-T01D | Real Integration and Acceptance | BLOCKED_ON_T01A+B+C | dispatch khi A/B/C MANAGER_VERIFIED |
| S11-T02..T06 | QCItem / Checks / Review Queue / Readiness Gate / Acceptance | **BLOCKED_ON_E06** | không mở packet/session |

## DAG

```
T01A ────────────────────────────┐
                                 ├─→ T01D
T01B ─→ T01C ────────────────────┘
```

## Frozen product decisions (parent prompt §8 + correction §4-7)

1. First audio stream là canonical; không trộn streams.
2. Video input: MP4 + H.264/HEVC (không nới).
3. AAC first audio: stream-copy khi an toàn.
4. Non-AAC first audio: source import với explicit warning; ATTACH_ORIGINAL_AUDIO transcode sang AAC.
5. No audio: explicit NO_AUDIO_PRESENT; không fabricated audio.
6. Corrupt/unsupported: fail closed; không silent fallback.
7. Source video không mutate; analysis generation không đổi.
8. Không Demucs/ASR/TTS/dubbing/QC/final-render UI/frontend trong T01.
9. S11 supersede duy nhất quyết định B5 non-AAC của VIDEO_PREFLIGHT_CONTRACT (append-only resolution).

## Worker model (user directive 2026-08-21 16:00+07)

Mọi session worker/reviewer MỚI của lane S11 dùng:
- model `alpha`, provider `custom` (9Router http://127.0.0.1:20128/v1)
- reasoning max (global agent.reasoning_effort=max)
- fallback disabled (không cấu hình fallback; route chết → báo user)

## Global-gate mutex

Không chạy global gate khi có writer đang ghi file hoặc S07 đang chạy global gate.
Focused tests song song chỉ khi temp DB/basetemp/managed root/port tách biệt.

## Terminal state mục tiêu

S11-T01A/B/C/D = MANAGER_VERIFIED → S11-T01 = MANAGER_VERIFIED_PENDING_CODEX_REVIEW
Sprint: IN_PROGRESS / T01_PENDING_CODEX_REVIEW / T02..T06_BLOCKED_ON_E06
KHÔNG tự ghi APPROVED/CLOSED/CODEX_APPROVED.
