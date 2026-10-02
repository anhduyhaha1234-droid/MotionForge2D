#!/usr/bin/env bash
# MF-END-22 write-set guard (v2): capture the BASE bytes from the disposable
# base WORKTREE (MF-END-22-verify-base @ 7cfdfa2 — same checkout line-ending
# convention as the writer's tree, so no autocrlf false positive), then verify
# the writer's tree: write-set changed only on its own paths, protected paths
# byte-identical, no destructive shrink.
set -u
PY="C:/Users/Admin/AppData/Local/Programs/Python/Python311/python.exe"
EV="C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-22"
WT="C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-22"
BASE="C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-22-verify-base"
GUARD="$EV/tools/write_set_guard.py"

cd "$WT" || exit 3

WRITE_SET=(
  "app/services/qc_evidence/measure.py"
  "app/services/qc_checks/contact_break.py"
  "app/services/qc_checks/z_order_error.py"
  "app/services/qc_checks/trajectory_drift.py"
  "app/services/qc_checks/identity_drift.py"
  "app/services/qc_checks/temporal_flicker.py"
  "tests/product_delivery/test_mf_end_22.py"
)
PROTECTED=(
  "app/services/rendered_observations.py"
  "app/services/qc_evidence/sources.py"
  "app/services/qc_evidence/observe.py"
  "app/services/source_interaction_facts.py"
  "app/services/source_role_tracks.py"
  "app/services/qc_checks/thresholds.py"
  "app/services/qc_checks/orchestrator.py"
  "app/services/qc_checks/runner.py"
  "app/services/qc_checks/registry.py"
  "tests/product_delivery/test_mf_end_21.py"
  "tests/product_delivery/test_mf_end_13.py"
  "tests/product_delivery/test_mf_end_12.py"
)

CAPTURE_ARGS=()
for path in "${WRITE_SET[@]}" "${PROTECTED[@]}"; do CAPTURE_ARGS+=(--path "$path"); done
"$PY" "$GUARD" capture --root "$BASE" \
  --manifest "$EV/write_set/write_set_before.json" "${CAPTURE_ARGS[@]}"

ALLOW_ARGS=()
for path in "${WRITE_SET[@]}"; do ALLOW_ARGS+=(--allow-change "$path"); done
"$PY" "$GUARD" verify --root "$WT" \
  --manifest "$EV/write_set/write_set_before.json" "${ALLOW_ARGS[@]}" \
  --report "$EV/write_set/write_set_after.json"

PROTECT_ARGS=()
for path in "${PROTECTED[@]}"; do PROTECT_ARGS+=(--path "$path"); done
"$PY" "$GUARD" capture --root "$BASE" \
  --manifest "$EV/write_set/protected_before.json" "${PROTECT_ARGS[@]}"
"$PY" "$GUARD" verify --root "$WT" \
  --manifest "$EV/write_set/protected_before.json" \
  --report "$EV/write_set/protected_after.json"
echo GUARD_DONE
