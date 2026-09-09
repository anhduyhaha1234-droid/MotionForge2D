@echo off
REM S12-T06A staged beta launcher — full lifecycle from a staged package.
REM Usage: Start-MotionForge-Beta.cmd PACKAGE_ROOT [RUNTIME_ROOT]
REM   PACKAGE_ROOT = owned dir containing manifest.json + scripts
REM   RUNTIME_ROOT = user-local dir for data/artifacts/output/logs
REM                 (default %%LOCALAPPDATA%%\MotionForge2D-beta-runtime)
REM External declared runtimes are probed, never installed/elevated.
setlocal EnableExtensions
if "%~1"=="" (
  echo Usage: %~nx0 PACKAGE_ROOT [RUNTIME_ROOT]
  exit /b 2
)
set "PACKAGE_ROOT=%~1"
set "RUNTIME_ROOT=%~2"
if "%RUNTIME_ROOT%"=="" set "RUNTIME_ROOT=%LOCALAPPDATA%\MotionForge2D-beta-runtime"
if not exist "%PACKAGE_ROOT%\manifest.json" (
  echo [s12-t06a] BLOCKED: PACKAGE_ROOT has no manifest.json: %PACKAGE_ROOT%
  exit /b 3
)
python "%PACKAGE_ROOT%\scripts\s12_t06a_run.py" serve --install-root "%RUNTIME_ROOT%"
endlocal