$ErrorActionPreference = "Continue"
$sessionRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = "C:\Users\Admin\MotionForge2D-worktrees\s06-t01-review"
$prompt = "Continue the S06-T05 pack review & publish UX task in this worktree. Read completely docs/pm/sessions/S06-T05-pack-publish-ux/START_PROMPT.md and TASK.md, inspect current git status and preserved work, implement only within the allowed write scope, run focused tests plus frontend checks and a fresh 7/7 baseline, update LOG.md and REPORT.md with real evidence, and end REPORT.md with SUBMITTED. Never self-approve. Do not commit, push, deploy, reset, checkout, clean, or delete data; do not touch channels.json, data/, database, or user data."
Set-Location $repoRoot
& hermes chat --query $prompt --source cli --max-turns 300 --provider custom --model ocg/deepseek-v4-flash --pass-session-id --checkpoints 2>&1 |
  Tee-Object -FilePath (Join-Path $sessionRoot "hermes-deepseek.log") -Append
exit $LASTEXITCODE
