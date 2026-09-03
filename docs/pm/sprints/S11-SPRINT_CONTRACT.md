# S11 SPRINT CONTRACT — Original Audio & Acceptance

**Status:** T01 CODEX_APPROVED; T02..T06 PRODUCTION_AUTHORIZED (19 IDs / 14 waves)
**Authority:** `S10_C6H_R3_FINAL_PM_REVIEW_2026-09-03.md` + `S11-P02 rev-C6 CODEX_APPROVED`; execution prompt `S11_T02_T06_FULL_SPRINT_MANAGER_2026-09-03.md`
**Canonical integration worktree:** C:\Users\Admin\MotionForge2D-worktrees\s11-integration (branch codex/s11-integration, clean checkpoint `4cec376bd7589bfd5bbd8c2260fdd63b751aca73`; Manager must rediscover actual HEAD)
**Read-only planning authority:** C:\Users\Admin\MotionForge2D-worktrees\s08-integration\output\s11-post-t01-readiness\r1\synthesis\S11_T02_T06_PRODUCTION_PLAN.md (SHA `342479267086485EF6FD44CB8B3A5F94E6F7B1AFCC4439AFDA2910068FC76F4F`)

## Task map

| Task | Tên | State | Ghi chú |
|---|---|---|---|
| S11-T01A | Audio Import Policy and Contract | CODEX_APPROVED | closed trong S11-T01 |
| S11-T01B | Original Audio Remux Engine | CODEX_APPROVED | closed trong S11-T01 |
| S11-T01C | Durable ATTACH_ORIGINAL_AUDIO Job Wiring | CODEX_APPROVED | closed trong S11-T01 |
| S11-T01D | Real Integration and Acceptance | CODEX_APPROVED | 64/64 approved suite |
| S11-T02..T06 | QCItem / Checks / Review Queue / Readiness Gate / Acceptance | **PRODUCTION_AUTHORIZED** | binding plan `output/s11-post-t01-readiness/r1/synthesis/S11_T02_T06_PRODUCTION_PLAN.md`, SHA 34247926..., 19 IDs / 14 waves |

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

## Worker model (latest user directive 2026-09-03)

Mọi session worker/reviewer MỚI của production T02..T06 dùng:
- exact model `ocg/deepseek-v4-flash`, provider `custom` (9Router)
- reasoning max (global agent.reasoning_effort=max)
- fallback disabled (không cấu hình fallback; route chết → báo user)

## Global-gate mutex

Không chạy global gate khi có writer đang ghi file hoặc S07 đang chạy global gate.
Focused tests song song chỉ khi temp DB/basetemp/managed root/port tách biệt.

## Isolated-worktree execution

- Mỗi production Task ID dùng một branch, clean worktree và Hermes session riêng
  từ exact integration HEAD của đầu wave; correction resume đúng session/branch.
- W6 chạy tối đa 4 implementation workers thật song song; W9 và W12 tối đa 2;
  các wave khác tuần tự theo DAG. Một writer duy nhất trong mỗi task worktree.
- Worker commit đúng exclusive allowlist + task-owned session docs trên local
  task branch rồi submit/exit. Commit chưa phải approval.
- Một integration owner `S11-INT01` duy nhất cherry-pick exact commit range đã
  Manager verify; zero manual conflict resolution, zero code edit. Conflict thì
  abort và trả exact task owner. Canonical branch được push sau wave gate xanh.
- Worktree `s08-integration` là read-only archive/evidence; không dispatch S11
  writer vào đó.

## Terminal state mục tiêu

Mỗi production Task ID sạch = MANAGER_VERIFIED_PENDING_SPRINT_REVIEW; Manager
tiếp tục dependency nội bộ theo full-sprint prompt. Sau T06C + exit gate:
`S11 = SPRINT_SUBMITTED / MANAGER_VERIFIED_PENDING_CODEX_REVIEW`.
KHÔNG tự ghi APPROVED/CLOSED/CODEX_APPROVED và không mở S12/S13.
