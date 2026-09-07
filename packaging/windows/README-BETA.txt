MotionForge 2D — Windows portable beta (S12-T06A harness)
===========================================================

QUICK START (no admin, no system changes):
  1. Install Python 3.11, Node.js 20+, FFmpeg (see docs\packaging\s12-windows.md).
  2. Install-MotionForge-Beta.cmd CODE_ROOT
  3. Start-MotionForge-Beta.cmd CODE_ROOT
  4. Open http://127.0.0.1:3121 (ports printed by serve; defaults 8421/3121).

STOP:  Stop-MotionForge-Beta.cmd CODE_ROOT
REMOVE: Uninstall-MotionForge-Beta.cmd CODE_ROOT  (keeps your data/ by default)

CODE_ROOT = the folder containing scripts\s12\s12_t06a_run.py.
Runtime data lives under %LOCALAPPDATA%\MotionForge2D-beta-runtime
(data/ artifacts/ output/ logs/ RUNTIME.json) — never in this folder.

Full guide: docs\packaging\s12-windows.md
