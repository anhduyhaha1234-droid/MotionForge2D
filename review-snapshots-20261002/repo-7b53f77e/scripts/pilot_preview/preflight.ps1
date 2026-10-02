param(
  [string]$SourceVideo = "",
  [string]$WorkRoot = ""
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
  @($WorkRoot, "work_root"), @($runtimeRoot, "runtime_root"), @($projectsRoot, "projects_root"),
  @($managedRoot, "managed_root"), @($tempRoot, "temp_root"), @($cacheRoot, "cache_root"),
  @($outputRoot, "output_root"), @($artifactsRoot, "artifacts_root"), @($modelsRoot, "models_root"),
  @($dbRoot, "db_root")
)) {
  Assert-IsolatedRoot $item[0] $item[1]
}
foreach ($item in @($runtimeRoot, $projectsRoot, $managedRoot, $tempRoot, $cacheRoot, $outputRoot, $artifactsRoot, $modelsRoot, $dbRoot)) {
  if (-not (Is-Descendant $item $WorkRoot)) { throw "runtime root escaped fresh WorkRoot: $item" }
}
if (Test-Path -LiteralPath $WorkRoot) {
  $existing = @(Get-ChildItem -LiteralPath $WorkRoot -Force -ErrorAction Stop)
  if ($existing | Where-Object { $_.Name -ne "runtime" }) { throw "WorkRoot contains non-runtime residue: $WorkRoot" }
  $runtimeExisting = @(Get-ChildItem -LiteralPath $runtimeRoot -Force -ErrorAction SilentlyContinue)
  if ($runtimeExisting | Where-Object { $_.Name -notin @("assets", "models") }) { throw "run root contains mutable runtime residue: $runtimeRoot" }
}
$asset = Join-Path $runtimeRoot "assets\v3-seated-rgba.png"
$checkpoint = Join-Path $runtimeRoot "models\sam2.1_hiera_large.pt"
$expectedAsset = "E07E2A3A76EA3D7D3144AE43F89EBBCC225A37CF91AA6AB159961F6D7349DC47"
$expectedCheckpoint = "2647878D5DFA5098F2F8649825738A9345572BAE2D4350A2468587ECE47DD318"

$result = [ordered]@{
  status = "PASS"
  repo_root = $repoRoot
  work_root = $WorkRoot
  runtime_root = $runtimeRoot
  projects_root = $projectsRoot
  managed_root = $managedRoot
  temp_root = $tempRoot
  cache_root = $cacheRoot
  output_root = $outputRoot
  artifacts_root = $artifactsRoot
  models_root = $modelsRoot
  db_root = $dbRoot
  ports = @{ backend = 8190; frontend = 3190 }
  source = $null
  asset = $null
  checkpoint = $null
  ffmpeg = $null
  ffprobe = $null
}

$evidenceDir = Join-Path $runtimeRoot "evidence"
foreach ($path in @($runtimeRoot, $projectsRoot, $managedRoot, $tempRoot, $cacheRoot, $outputRoot, $artifactsRoot, $modelsRoot, $dbRoot, $evidenceDir)) {
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
$env:MOTIONFORGE_MODELS = $modelsRoot
$env:MOTIONFORGE_OUTPUT = $outputRoot
$env:MOTIONFORGE_TEMP = $tempRoot
$env:MOTIONFORGE_CACHE = $cacheRoot
$env:MOTIONFORGE_MANAGED_ROOT = $managedRoot

foreach ($path in @($asset, $checkpoint)) {
  if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing runtime input: $path" }
}
$assetHash = (Get-FileHash -LiteralPath $asset -Algorithm SHA256).Hash
$checkpointHash = (Get-FileHash -LiteralPath $checkpoint -Algorithm SHA256).Hash
$result.asset = @{ path = $asset; sha256 = $assetHash; matches_pin = ($assetHash -eq $expectedAsset) }
$result.checkpoint = @{ path = $checkpoint; sha256 = $checkpointHash; matches_pin = ($checkpointHash -eq $expectedCheckpoint) }
if ($assetHash -ne $expectedAsset -or $checkpointHash -ne $expectedCheckpoint) { throw "Pinned runtime input hash mismatch" }

if ($SourceVideo) {
  if (-not (Test-Path -LiteralPath $SourceVideo -PathType Leaf)) { throw "Missing source video: $SourceVideo" }
  $sourceHash = (Get-FileHash -LiteralPath $SourceVideo -Algorithm SHA256).Hash
  $result.source = @{ path = (Resolve-Path -LiteralPath $SourceVideo).Path; sha256 = $sourceHash }
}

foreach ($name in @("ffmpeg", "ffprobe")) {
  $command = Get-Command $name -ErrorAction SilentlyContinue
  if ($command) {
    $stdout = [System.IO.Path]::GetTempFileName()
    $stderr = [System.IO.Path]::GetTempFileName()
    try {
      $probe = Start-Process -FilePath $command.Source -ArgumentList @("-version") -RedirectStandardOutput $stdout -RedirectStandardError $stderr -Wait -PassThru -WindowStyle Hidden
      if ($probe.ExitCode -ne 0) { throw "exit code $($probe.ExitCode): $((Get-Content -LiteralPath $stderr -Raw -ErrorAction SilentlyContinue).Trim())" }
      $result[$name] = @{ path = $command.Source; available = $true; executable = $true; version = (Get-Content -LiteralPath $stdout -TotalCount 1 -ErrorAction SilentlyContinue) }
    } catch {
      $result[$name] = @{ path = $command.Source; available = $true; executable = $false; error = $_.Exception.Message }
      $result.status = "BLOCKED_FFMPEG_EXECUTION"
    } finally {
      Remove-Item -LiteralPath $stdout, $stderr -Force -ErrorAction SilentlyContinue
    }
  } else {
    $result[$name] = @{ path = $null; available = $false; executable = $false }
    $result.status = "BLOCKED_FFMPEG_UNAVAILABLE"
  }
}

$out = Join-Path $evidenceDir "pilot-preview-preflight.json"
$result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $out -Encoding UTF8
$result | ConvertTo-Json -Depth 8
