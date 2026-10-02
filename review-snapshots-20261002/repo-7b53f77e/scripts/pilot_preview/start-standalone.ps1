param(
  [string]$WorkRoot = "",
  [int]$BackendPort = 8190,
  [int]$FrontendPort = 3190
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if (-not $WorkRoot) { throw "WorkRoot is required: pass a fresh isolated run root explicitly" }
$repoRoot = [IO.Path]::GetFullPath($repoRoot)
$WorkRoot = [IO.Path]::GetFullPath($WorkRoot)
$runtimeRoot = [IO.Path]::GetFullPath((Join-Path $WorkRoot "runtime"))
$projectsRoot = [IO.Path]::GetFullPath((Join-Path $runtimeRoot "projects"))
$managedRoot = [IO.Path]::GetFullPath((Join-Path $runtimeRoot "managed"))
$tempRoot = [IO.Path]::GetFullPath((Join-Path $runtimeRoot "temp"))
$cacheRoot = [IO.Path]::GetFullPath((Join-Path $runtimeRoot "cache"))
$outputRoot = [IO.Path]::GetFullPath((Join-Path $runtimeRoot "output"))
$artifactsRoot = [IO.Path]::GetFullPath((Join-Path $runtimeRoot "artifacts"))
$modelsRoot = [IO.Path]::GetFullPath((Join-Path $runtimeRoot "models"))
$dbRoot = [IO.Path]::GetFullPath((Join-Path $runtimeRoot "data"))

function Is-Descendant([string]$Candidate, [string]$Parent) {
  $candidateFull = [IO.Path]::GetFullPath($Candidate).TrimEnd('\')
  $parentFull = [IO.Path]::GetFullPath($Parent).TrimEnd('\')
  return $candidateFull.StartsWith($parentFull + '\', [StringComparison]::OrdinalIgnoreCase)
}

function Assert-IsolatedRoot([string]$Path, [string]$Label) {
  if (-not [IO.Path]::IsPathRooted($Path)) { throw "$Label must be absolute: $Path" }
  $full = [IO.Path]::GetFullPath($Path)
  if ($full -eq $repoRoot -or (Is-Descendant $full $repoRoot)) { throw "$Label cannot be the repository or a repository descendant: $full" }
  $protectedRoots = @(
    (Join-Path $env:USERPROFILE "MotionForge2D"),
    (Join-Path $env:USERPROFILE "MotionForge2D-worktrees\s11-integration"),
    (Join-Path $env:USERPROFILE "MotionForge2D-worktrees\s12"),
    (Join-Path $env:USERPROFILE "MotionForge2D-worktrees\s12-integration"),
    (Join-Path $env:USERPROFILE "MotionForge2D-evidence\MAIN"),
    (Join-Path $env:USERPROFILE "MotionForge2D-evidence\S11"),
    (Join-Path $env:USERPROFILE "MotionForge2D-evidence\S12")
  )
  $worktreesRoot = Join-Path $env:USERPROFILE "MotionForge2D-worktrees"
  if (Test-Path -LiteralPath $worktreesRoot -PathType Container) {
    $protectedRoots += @(Get-ChildItem -LiteralPath $worktreesRoot -Directory -Force -ErrorAction SilentlyContinue |
      Where-Object { $_.Name -like "s12-*" } |
      ForEach-Object { $_.FullName })
  }
  foreach ($protected in $protectedRoots) {
    if ($full -eq ([IO.Path]::GetFullPath($protected)).TrimEnd('\') -or (Is-Descendant $full $protected)) {
      throw "$Label is inside protected MAIN/S11/S12 data: $full"
    }
  }
}
foreach ($item in @(
  @($WorkRoot, "work_root"), @($runtimeRoot, "runtime_root"),
  @($projectsRoot, "projects_root"), @($managedRoot, "managed_root"),
  @($tempRoot, "temp_root"), @($cacheRoot, "cache_root"), @($outputRoot, "output_root"),
  @($artifactsRoot, "artifacts_root"), @($modelsRoot, "models_root"), @($dbRoot, "db_root")
)) { Assert-IsolatedRoot $item[0] $item[1] }
foreach ($item in @($runtimeRoot, $projectsRoot, $managedRoot, $tempRoot, $cacheRoot, $outputRoot, $artifactsRoot, $modelsRoot, $dbRoot)) {
  if (-not (Is-Descendant $item $WorkRoot)) { throw "runtime root escaped fresh WorkRoot: $item" }
}
if (Test-Path -LiteralPath $WorkRoot) {
  $existing = @(Get-ChildItem -LiteralPath $WorkRoot -Force -ErrorAction Stop)
  if ($existing | Where-Object { $_.Name -ne "runtime" }) { throw "WorkRoot contains non-runtime residue: $WorkRoot" }
  $runtimeExisting = @(Get-ChildItem -LiteralPath $runtimeRoot -Force -ErrorAction SilentlyContinue)
  if ($runtimeExisting | Where-Object { $_.Name -notin @("assets", "models") }) { throw "run root contains mutable runtime residue: $runtimeRoot" }
}

$protectedPorts = @(3187, 8187, 18769, 3188, 8188, 3189, 8189)
foreach ($port in @($BackendPort, $FrontendPort)) {
  if ($port -in $protectedPorts) { throw "Requested port is protected: $port" }
  if ($port -lt 1024 -or $port -gt 65535) { throw "Requested port is invalid: $port" }
  $listener = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
  if ($listener.Count -gt 0) { throw "Requested port is already listening: $port" }
}

foreach ($path in @($runtimeRoot, $projectsRoot, $artifactsRoot, $modelsRoot, $outputRoot, $managedRoot, $tempRoot, $cacheRoot, $dbRoot)) {
  New-Item -ItemType Directory -Force -Path $path | Out-Null
}

$env:TEMP = $tempRoot
$env:TMP = $tempRoot
$env:PYTHONPYCACHEPREFIX = Join-Path $cacheRoot "pycache"
$env:PIP_CACHE_DIR = Join-Path $cacheRoot "pip"
$env:XDG_CACHE_HOME = $cacheRoot
$env:MOTIONFORGE_QA_MODE = "1"
$env:MOTIONFORGE_ROOT = $projectsRoot
$env:MOTIONFORGE_PROJECT_ROOT = $projectsRoot
$env:MOTIONFORGE_MODELS = Join-Path $runtimeRoot "models"
$env:MOTIONFORGE_OUTPUT = Join-Path $runtimeRoot "output"
$env:MOTIONFORGE_TEMP = $tempRoot
$env:MOTIONFORGE_CACHE = $cacheRoot
$env:MOTIONFORGE_MANAGED_ROOT = $managedRoot
$env:MOTIONFORGE_PILOT_RUN_ROOT = $WorkRoot
$env:MOTIONFORGE_CORS_ORIGINS = "http://127.0.0.1:$FrontendPort,http://localhost:$FrontendPort"
$env:NEXT_PUBLIC_API_URL = "http://127.0.0.1:$BackendPort"

$backend = Start-Process -FilePath "python" -ArgumentList "-m","uvicorn","app.main:app","--host","127.0.0.1","--port",$BackendPort -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru
$frontend = Start-Process -FilePath "npm" -ArgumentList "run","dev","--","--hostname","127.0.0.1","--port",$FrontendPort -WorkingDirectory (Join-Path $repoRoot "frontend") -WindowStyle Hidden -PassThru

try {
  $backendReady = $false
  for ($attempt = 0; $attempt -lt 30; $attempt++) {
    if ($backend.HasExited) { throw "backend exited before health check (pid $($backend.Id))" }
    try {
      $health = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$BackendPort/health" -TimeoutSec 2
      if ($health.StatusCode -eq 200) { $backendReady = $true; break }
    } catch { }
    Start-Sleep -Seconds 1
  }
  if (-not $backendReady) { throw "backend health check timed out" }
  $frontendReady = $false
  for ($attempt = 0; $attempt -lt 30; $attempt++) {
    if ($frontend.HasExited) { throw "frontend exited before health check (pid $($frontend.Id))" }
    try {
      $page = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$FrontendPort/pilot-preview" -TimeoutSec 2
      if ($page.StatusCode -ge 200 -and $page.StatusCode -lt 500) { $frontendReady = $true; break }
    } catch { }
    Start-Sleep -Seconds 1
  }
  if (-not $frontendReady) { throw "frontend health check timed out" }
} catch {
  foreach ($process in @($backend, $frontend)) {
    if ($process -and -not $process.HasExited) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
  }
  throw
}

Write-Output (ConvertTo-Json @{ backend_pid = $backend.Id; frontend_pid = $frontend.Id; backend_url = "http://127.0.0.1:$BackendPort"; pilot_preview_url = "http://127.0.0.1:$FrontendPort/pilot-preview" } -Depth 4)
