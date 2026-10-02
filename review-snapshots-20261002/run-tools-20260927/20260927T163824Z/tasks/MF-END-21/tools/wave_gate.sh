#!/usr/bin/env bash
# MF-END-21 wave gate: focused -> static -> ONE broad wave, each logged to
# commands.jsonl via tools/logcmd.py.  Outputs also frozen under raw/.
set -u
PY="C:/Users/Admin/AppData/Local/Programs/Python/Python311/python.exe"
EV="C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-21"
WT="C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-21"
cd "$WT" || exit 3

"$PY" -B "$EV/tools/logcmd.py" focused "$PY" -m pytest -q tests/product_delivery/test_mf_end_21.py
"$PY" -B "$EV/tools/logcmd.py" ruff "$PY" -m ruff check app/services/rendered_observations.py app/services/qc_evidence/sources.py app/services/qc_evidence/observe.py tests/product_delivery/test_mf_end_21.py
"$PY" -B "$EV/tools/logcmd.py" py_compile "$PY" -m py_compile app/services/rendered_observations.py app/services/qc_evidence/sources.py app/services/qc_evidence/observe.py tests/product_delivery/test_mf_end_21.py
"$PY" -B "$EV/tools/logcmd.py" broad_product_delivery bash -c "'$PY' -m pytest -q tests/product_delivery > '$EV/raw/broad_product_delivery.txt' 2>&1"
"$PY" -B "$EV/tools/logcmd.py" broad_public_chain bash -c "'$PY' -m pytest -q tests/product_p1/public_chain > '$EV/raw/broad_public_chain.txt' 2>&1"
echo WAVE_GATE_DONE
