@echo off
REM S12-T06A stage installer — build a relocatable staged beta package.
REM Usage: Install-MotionForge-Beta.cmd STAGE_ROOT [BACKEND_PORT] [FRONTEND_PORT]
REM   STAGE_ROOT   owned absolute path OUTSIDE the repo checkout and
REM                outside %%USERPROFILE%%\MotionForge2D (refused otherwise)
REM Produces manifest.json + backend/ + frontend/ + scripts/ + launchers.
REM External declared runtimes (Python 3.11, Node.js 20+, FFmpeg, npm)
REM are probed and used; nothing is installed/elevated/downloaded.
setlocal EnableExtensions
if "%~1"=="" (
  echo Usage: %~nx0 STAGE_ROOT [BACKEND_PORT] [FRONTEND_PORT]
  exit /b 2
)
set "STAGE_ROOT=%~1"
set "BPORT=%~2"
set "FPORT=%~3"
if "%BPORT%"=="" set "BPORT=8421"
if "%FPORT%"=="" set "FPORT=3121"
set "SRC=%~dp0"
set "REPO_ROOT=%SRC%..\..\"
python "%REPO_ROOT%scripts\s12\s12_t06a_stage.py" --stage-root "%STAGE_ROOT%" --backend-port %BPORT% --frontend-port %FPORT%
if errorlevel 1 (
  echo [s12-t06a] BLOCKED: stage failed — resolve the BLOCKER, never waive.
  exit /b 3
)
echo [s12-t06a] installed. Start with:
echo   Start-MotionForge-Beta.cmd "%STAGE_ROOT%"
endlocal