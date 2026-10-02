#!/bin/bash
# TRUE LAST WRITE ORDER: run the final gate, then rebuild the manifest as the
# very last write, then verify READ-ONLY. Any file written after the manifest
# would invalidate it, so nothing may write into RUN after step 2.
set -u
RUN="C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260930/20260930T165243Z"
T="$RUN/manager/tools"

echo "STEP 1/3: final gate -> $RUN/manager/T020_FINAL.txt"
bash "$T/absolute_final.sh" >/dev/null 2>&1
tail -1 "$RUN/manager/T020_FINAL.txt"

echo "STEP 2/3: rebuild manifest (deterministic builder)"
cd "$T" && python -B evidence_manifest.py
cd "$T" && python -B evidence_manifest.py   # second run proves determinism

echo "STEP 3/3: verify READ-ONLY against the frozen tree"
cd "$T" && python -B evidence_manifest.py verify > "$RUN/manager/T023_manifest_verify.txt" 2>&1; cat "$RUN/manager/T023_manifest_verify.txt"
