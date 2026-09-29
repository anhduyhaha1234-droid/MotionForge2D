param(
  [Parameter(Mandatory = $true)][string]$Candidate,
  [Parameter(Mandatory = $true)][string]$RepoRoot,
  [Parameter(Mandatory = $true)][string]$WorkRoot
)

$ErrorActionPreference = "Stop"

function Is-Descendant([string]$Child, [string]$Parent) {
  $childFull = [IO.Path]::GetFullPath($Child).TrimEnd('\')
  $parentFull = [IO.Path]::GetFullPath($Parent).TrimEnd('\')
  return $childFull.StartsWith($parentFull + '\', [StringComparison]::OrdinalIgnoreCase)
}

$candidateFull = [IO.Path]::GetFullPath($Candidate)
$repoFull = [IO.Path]::GetFullPath($RepoRoot)
$workFull = [IO.Path]::GetFullPath($WorkRoot)
if ($candidateFull -eq $repoFull -or (Is-Descendant $candidateFull $repoFull)) {
  throw "candidate is the repository or a repository descendant: $candidateFull"
}
if (-not (Is-Descendant $candidateFull $workFull)) {
  throw "candidate is outside the fresh work root: $candidateFull"
}
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
  if ($candidateFull -eq ([IO.Path]::GetFullPath($protected)).TrimEnd('\') -or (Is-Descendant $candidateFull $protected)) {
    throw "candidate is inside protected MAIN/S11/S12 data: $candidateFull"
  }
}
Write-Output (ConvertTo-Json @{ status = "PASS"; candidate = $candidateFull; repo_root = $repoFull; work_root = $workFull } -Depth 3)
