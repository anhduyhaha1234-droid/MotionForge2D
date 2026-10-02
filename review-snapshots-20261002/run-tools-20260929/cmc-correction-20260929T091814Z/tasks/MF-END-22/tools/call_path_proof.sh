#!/usr/bin/env bash
# MF-END-22 C22 — call-path proof: BEFORE (base) vs AFTER (HEAD).
WT="C:/Users/Admin/Documents/Codex/work/mf-delivery-20260929/C22"
EV="C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260929/cmc-correction-20260929T091814Z/tasks/MF-END-22"
OUT="$EV/raw/call_path_grep.txt"
cd "$WT" || exit 1
PAT='compare_contact_facts|compare_occlusion_facts|compare_motion_facts|compare_identity_facts|compare_static_and_flicker'
EXCL='qc_checks/contact_break.py|qc_checks/z_order_error.py|qc_checks/trajectory_drift.py|qc_checks/identity_drift.py|qc_checks/temporal_flicker.py|qc_evidence/measure.py'
{
  echo "### BEFORE (base a52fca8) — calls OUTSIDE the 5 defining modules + measure.py"
  git grep -n -E "$PAT" a52fca8 -- app | grep -Ev "$EXCL" || echo "(none)"
  echo "BEFORE_CALLER_LINES=$(git grep -n -E "$PAT" a52fca8 -- app | grep -Evc "$EXCL" || echo 0)"
  echo
  echo "### AFTER (HEAD) — call sites in the production path"
  grep -n -E 'compare_.*_facts|compare_static_and_flicker' app/services/qc_evidence/compose.py
  grep -n -E '_comparison_band_report|compose_comparison_band|comparison_band=comparison_band' app/workflow/qc_checks_handler.py
  echo "AFTER_CALLER_LINES=$(grep -cE 'compare_.*_facts|compare_static_and_flicker' app/services/qc_evidence/compose.py)"
} > "$OUT" 2>&1
echo "WROTE $OUT"
