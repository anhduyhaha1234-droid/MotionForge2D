@echo off
REM S12-T06A portable beta launcher — starts backend + compiled frontend.
REM Usage: Start-MotionForge-Beta.cmd CODE_ROOT [RUNTIME_ROOT]
setlocal EnableExtensions
if "%~1"=="" (
  echo Usage: %~nx0 CODE_ROOT [RUNTIME_ROOT]
  exit /b 2
)
set "CODE_ROOT=%~1"
set "RUNTIME_ROOT=%~2"
if "%RUNTIME_ROOT%"=="" set "RUNTIME_ROOT=%LOCALAPPDATA%\MotionForge2D-beta-runtime"
python "%CODE_ROOT%\scripts\s12\s12_t06a_run.py" serve --install-root "%RUNTIME_ROOT%"
endlocal
