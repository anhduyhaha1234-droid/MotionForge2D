# S12-T03A LOG — C1 correction (owner 20260907_094835_159075)

## 2026-09-08 06:24 +07 — C1 closure rows (TASK_SUBMITTED)

### Scope C1 §4 T03A ONLY
- `tests/s12/s12-t03a/test_c1_closure.py` (NEW, 14 tests): C06
  replay-material-identity (5) + C07 identity-union-orphan (5) + C08
  two-participant claim/transition (2: Barrier race + stale-ORM
  sequential control) + C09 live-lease-fencing (2). Isolated fixtures,
  temp roots `s12t03a_c1_*`, no case removal (30 tests cũ giữ nguyên).
- `app/persistence/s12_export.py` (bounded fix, không schema change →
  KHÔNG migration mới, `c3d4e5f6a7b8` giữ nguyên sole head): `claim_run`
  re-claim/claim trên run `running` không còn ép `pending → running`
  (chỉ activate khi pending; defensive raise otherwise). Root cause từ
  real output: C07 orphan-repair re-claim fresh lease trên run running
  → `_activate_run(expected="pending")` raise sai.
- C07 orphan direction sửa theo FK thật: RESTRICT lease→run nên orphan
  thật = lease row mất, run survives (không phải ngược lại); re-claim
  repair đúng một lần, fresh lease version restart = 1.
- Ruff F841 ×2 (v1, lease1 thừa sau sửa test) → xóa, sạch.

### Gates (exact)
- `python -m pytest tests/s12/s12-t03a/ -q -p no:cacheprovider` →
  **44 passed in 51.47s** (30 cũ + 14 C1), exit 0.
- `ruff check --select F` (5 files incl. closure) → All checks passed.
- `git diff --check` → exit 0.
- Sole head `c3d4e5f6a7b8` unchanged (no migration this correction).
- Pre-existing 3 bootstrap table-set fails: không chạm, không regression.
