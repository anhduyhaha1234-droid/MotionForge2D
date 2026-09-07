@echo off
REM S12-T06A portable beta installer — user-local, no elevation.
REM Staged dir layout (this folder): manifest.json, README-BETA.txt,
REM Start/Stop/Uninstall .cmd launchers. The CODE tree (backend + compiled
REM frontend) is the repo checkout the beta was staged from; the installer
REM records its path and creates a user-local RUNTIME root. It never
REM touches PATH, firewall, registry, or system locations, and never
REM requires elevation.
setlocal EnableExtensions
if "%~1"=="" (
  echo Usage: %~nx0 CODE_ROOT [RUNTIME_ROOT]
  echo   CODE_ROOT     repo checkout containing scripts\s12\s12_t06a_run.py
  echo   RUNTIME_ROOT  user-local dir ^(default %%LOCALAPPDATA%%\MotionForge2D-beta-runtime^)
  exit /b 2
)
set "CODE_ROOT=%~1"
set "RUNTIME_ROOT=%~2"
if "%RUNTIME_ROOT%"=="" set "RUNTIME_ROOT=%LOCALAPPDATA%\MotionForge2D-beta-runtime"
if not exist "%CODE_ROOT%\scripts\s12\s12_t06a_run.py" (
  echo [s12-t06a] BLOCKED: CODE_ROOT has no scripts\s12\s12_t06a_run.py: %CODE_ROOT%
  exit /b 3
)
if not exist "%CODE_ROOT%\packaging\windows\manifest.json" (
  echo [s12-t06a] BLOCKED: CODE_ROOT has no packaging\windows\manifest.json
  exit /b 3
)
echo [s12-t06a] code root:    %CODE_ROOT%
echo [s12-t06a] runtime root: %RUNTIME_ROOT%
python "%CODE_ROOT%\scripts\s12\s12_t06a_run.py" setup --install-root "%RUNTIME_ROOT%"
if errorlevel 1 (
  echo [s12-t06a] BLOCKED: setup failed — resolve the BLOCKER above, never waive.
  exit /b 3
)
echo [s12-t06a] installed. Start with:
echo   python "%CODE_ROOT%\scripts\s12\s12_t06a_run.py" serve --install-root "%RUNTIME_ROOT%"
endlocal
