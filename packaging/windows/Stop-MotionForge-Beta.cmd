@echo off
REM S12-T06A staged beta stop — graceful shutdown (frontend, then backend)
REM with process-identity guard: reused/wrong PIDs are never killed; a
REM failed stop retains evidence and returns nonzero.
REM Usage: Stop-MotionForge-Beta.cmd PACKAGE_ROOT [RUNTIME_ROOT]
setlocal EnableExtensions
if "%~1"=="" (
  echo Usage: %~nx0 PACKAGE_ROOT [RUNTIME_ROOT]
  exit /b 2
)
set "PACKAGE_ROOT=%~1"
set "RUNTIME_ROOT=%~2"
if "%RUNTIME_ROOT%"=="" set "RUNTIME_ROOT=%LOCALAPPDATA%\MotionForge2D-beta-runtime"
python "%PACKAGE_ROOT%\scripts\s12_t06a_run.py" stop --install-root "%RUNTIME_ROOT%"
endlocal