@echo off
REM S12-T06A staged beta uninstall — cleanup; user data KEPT by default.
REM Usage: Uninstall-MotionForge-Beta.cmd PACKAGE_ROOT [RUNTIME_ROOT]
REM Refuses to delete data/ artifacts/ output/ without an explicit
REM --confirm-remove-data flag (run.py), preserving user data by default.
setlocal EnableExtensions
if "%~1"=="" (
  echo Usage: %~nx0 PACKAGE_ROOT [RUNTIME_ROOT]
  exit /b 2
)
set "PACKAGE_ROOT=%~1"
set "RUNTIME_ROOT=%~2"
if "%RUNTIME_ROOT%"=="" set "RUNTIME_ROOT=%LOCALAPPDATA%\MotionForge2D-beta-runtime"
python "%PACKAGE_ROOT%\scripts\s12_t06a_run.py" uninstall --install-root "%RUNTIME_ROOT%"
endlocal