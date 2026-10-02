#!/usr/bin/env bash
# MF-END-22 (C22 correction) write-set guard: capture BASE bytes from a
# disposable worktree at the pinned base, then verify the writer's tree.
set -u
EV="C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260929/cmc-correction-20260929T091814Z/tasks/MF-END-22"
WT="C:/Users/Admin/Documents/Codex/work/mf-delivery-20260929/C22"
BASE="a52fca897906fd61a088016dd802718fdf06d217"
G="C:/Users/Admin/MotionForge2D/docs/pm/tools/write_set_guard.py"
PY="C:/Users/Admin/AppData/Local/Programs/Python/Python311/python.exe"
BASE_WT="C:/Users/Admin/Documents/Codex/work/mf-delivery-20260929/C22-verify-base"
WRITE_SET=(
  app/services/qc_evidence/measure.py
  app/services/qc_checks/contact_break.py
  app/services/qc_checks/z_order_error.py
  app/services/qc_checks/trajectory_drift.py
  app/services/qc_checks/identity_drift.py
  app/services/qc_checks/temporal_flicker.py
  app/services/qc_evidence/compose.py
  app/services/qc_checks/orchestrator.py
  app/workflow/qc_checks_handler.py
  app/persistence/qc_check_runs.py
)
PROTECTED=(
  app/services/rendered_observations.py
  app/services/source_interaction_facts.py
  app/services/source_role_tracks.py
  app/services/qc_evidence/sources.py
  app/services/qc_evidence/observe.py
  app/services/qc_checks/thresholds.py
  tests/product_delivery/test_mf_end_22.py
)
which="${1:-capture}"
if [ "$which" = "capture" ]; then
  if [ ! -d "$BASE_WT" ]; then
    git -C "$WT" worktree add --detach "$BASE_WT" "$BASE" >/dev/null 2>&1
  fi
  ARGS=()
  for p in "${WRITE_SET[@]}" "${PROTECTED[@]}"; do ARGS+=(--path "$p"); done
  "$PY" "$G" capture --root "$BASE_WT" --manifest "$EV/write_set/write_set_before.json" \
    --snapshot-dir "$EV/write_set/snapshots" "${ARGS[@]}" && echo CAPTURE_RC=0
else
  ALLOW=()
  for p in "${WRITE_SET[@]}"; do ALLOW+=(--allow-change "$p"); done
  "$PY" "$G" verify --root "$WT" --manifest "$EV/write_set/write_set_before.json" \
    --report "$EV/write_set/write_set_guard_after.json" "${ALLOW[@]}" && echo VERIFY_RC=0
fi
