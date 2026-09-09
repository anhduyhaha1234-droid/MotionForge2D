MotionForge 2D — Windows staged beta (S12-T06A C2)
====================================================

This is a STAGED PACKAGE, not a fully self-contained portable build.
It bundles the built frontend (.next) + backend artifacts and declares
the EXTERNAL runtimes it needs; it never installs, downloads, elevates,
or edits PATH/registry/firewall/ACL.

QUICK START:
  1. Ensure declared runtimes on PATH: Python 3.11, Node.js 20+, FFmpeg.
  2. Install-MotionForge-Beta.cmd STAGE_ROOT [BACKEND_PORT] [FRONTEND_PORT]
     -> builds the stage (rebuilds frontend with the backend port baked).
  3. Start-MotionForge-Beta.cmd PACKAGE_ROOT [RUNTIME_ROOT]
     -> setup preflight (fail-closed) + serve; open the printed URL.
  4. Diagnose-MotionForge-Beta? run:
     python PACKAGE_ROOT\scripts\s12_t06a_run.py diagnose --install-root RUNTIME_ROOT
  5. Stop-MotionForge-Beta.cmd PACKAGE_ROOT [RUNTIME_ROOT]
     -> graceful shutdown, process-identity guarded (reused/wrong PIDs
        never killed; failed stop keeps evidence + nonzero exit).
  6. Uninstall-MotionForge-Beta.cmd PACKAGE_ROOT [RUNTIME_ROOT]
     -> keeps data/ artifacts/ output/ by default.

RUNTIME_ROOT defaults to %LOCALAPPDATA%\MotionForge2D-beta-runtime
(data/, artifacts/, output/, logs/, RUNTIME.json) — user-local, never
inside the package tree.

Full guide: docs/packaging/s12-windows.md