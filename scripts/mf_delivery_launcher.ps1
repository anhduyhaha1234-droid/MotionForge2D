<#
.SYNOPSIS
  MotionForge 2D — demo delivery launcher (MF-END-28).

.DESCRIPTION
  Launches the MotionForge demo stack (backend + frontend) as HIDDEN
  helper processes from ANY working directory, with health / port /
  model checks.  Every path is derived from $PSScriptRoot or parameters;
  nothing resolves relative to the caller's current directory.

  Two layouts are supported:
    * staged package : <PackageRoot>\manifest.json + backend\ + frontend\
                       (produced by scripts/s12/s12_t06a_stage.py)
    * repo checkout  : <PackageRoot>\app + <PackageRoot>\frontend
                       (default PackageRoot = the repo containing this
                        script, i.e. <script>\.. )

  Declared external runtimes (Python 3.11, Node.js 20+, FFmpeg) are
  probed, never installed, never elevated.  Model weights stay in an
  EXTERNAL read-only root declared by packaging/demo/models.json; nothing
  is copied into the package or the checkout.  A missing model is a
  typed MODEL_MISSING blocker (exit 3) — never waived.

  Process safety: each spawned process is recorded with {pid,
  creation_time, executable, command, token}; `stop` re-probes the live
  identity and NEVER kills a reused/wrong pid — it refuses, keeps the
  record and returns non-zero.

  Actions:
    check  : package + ports + toolchain + models.  No processes, no writes.
    start  : check (must pass), then spawn hidden backend+frontend, wait
             for health, write launcher_state.json under RuntimeRoot.
    status : read state, re-probe identity of recorded pids + HTTP health.
    stop   : identity-guarded stop of ONLY the recorded pids.

  Machine-readable output: a final line `LAUNCHER_JSON={...}` on stdout.
  Exit codes: 0 ok / 3 typed blocked or not-run / 2 usage error.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\mf_delivery_launcher.ps1 `
      -Action check -ModelsRoot D:\mf-models
.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\mf_delivery_launcher.ps1 `
      -Action start -PackageRoot C:\stage\mf-demo -RuntimeRoot $env:LOCALAPPDATA\MotionForge2D-demo-runtime
#>
[CmdletBinding()]
param(
    [ValidateSet('check', 'start', 'status', 'stop')]
    [string]$Action = 'check',
    [string]$PackageRoot = '',
    [string]$RuntimeRoot = '',
    [int]$BackendPort = 0,
    [int]$FrontendPort = 0,
    [string]$ModelsRoot = '',
    [string]$ModelsManifest = '',
    [int]$HealthTimeoutSec = 120
)

$ErrorActionPreference = 'Stop'
$script:Schema = 'mf2d-demo-launcher/1'
$script:Findings = New-Object System.Collections.ArrayList
# Capture the script location ONCE at script scope: $MyInvocation inside a
# function does not carry the script path (classic PS trap), and $PSScriptRoot
# is only reliable at script scope.
if ($PSScriptRoot) {
    $script:ScriptDir = $PSScriptRoot
} else {
    $script:ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
}
$script:RepoRoot = Split-Path -Parent $script:ScriptDir

function Add-Finding([string]$Code, [string]$Detail, [string]$Level) {
    # Level: blocker | warn | info
    [void]$script:Findings.Add(@{ code = $Code; level = $Level; detail = $Detail })
}

function Emit-Json([hashtable]$Payload) {
    $compact = $Payload | ConvertTo-Json -Depth 8 -Compress
    # Direct console write: `$code = Some-Function` would otherwise CAPTURE
    # anything written via Write-Output (classic PS pipeline capture) and the
    # machine-readable line would never reach stdout.
    [Console]::Out.WriteLine('LAUNCHER_JSON=' + $compact)
}

function Get-ScriptDirs {
    return @{ script_dir = $script:ScriptDir; repo_root = $script:RepoRoot }
}

function Resolve-PackageRoot([string]$Raw) {
    $dirs = Get-ScriptDirs
    if ([string]::IsNullOrWhiteSpace($Raw)) {
        return $dirs.repo_root
    }
    if (-not (Test-Path -LiteralPath $Raw)) {
        throw "PackageRoot does not exist: $Raw"
    }
    return (Resolve-Path -LiteralPath $Raw).Path
}

function Resolve-RuntimeRoot([string]$Raw) {
    if (-not [string]::IsNullOrWhiteSpace($Raw)) {
        return $Raw
    }
    $base = $env:LOCALAPPDATA
    if ([string]::IsNullOrWhiteSpace($base)) { $base = $env:TEMP }
    return (Join-Path $base 'MotionForge2D-demo-runtime')
}

function Get-LayoutInfo([string]$Pkg) {
    $staged = Test-Path -LiteralPath (Join-Path $Pkg 'backend\app')
    $manifest = Join-Path $Pkg 'manifest.json'
    $info = @{
        layout = 'repo'
        package_root = $Pkg
        backend_dir = $Pkg
        frontend_dir = Join-Path $Pkg 'frontend'
        manifest_path = $manifest
        manifest = $null
    }
    if ($staged) {
        $info.layout = 'staged'
        $info.backend_dir = Join-Path $Pkg 'backend'
        $info.frontend_dir = Join-Path $Pkg 'frontend'
    }
    if (Test-Path -LiteralPath $manifest) {
        try {
            $info.manifest = Get-Content -LiteralPath $manifest -Raw | ConvertFrom-Json
        } catch {
            $info.manifest = $null
        }
    }
    return $info
}

function Test-PortOpen([int]$Port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $iar = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
        if (-not $iar.AsyncWaitHandle.WaitOne(600)) { return $false }
        $client.EndConnect($iar)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Test-HttpOk([string]$Url, [int]$TimeoutSec) {
    try {
        $resp = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec $TimeoutSec
        return ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 400)
    } catch {
        return $false
    }
}

function Wait-Http([string]$Url, [int]$TimeoutSec, [string]$Label) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-HttpOk -Url $Url -TimeoutSec 4) { return $true }
        Start-Sleep -Seconds 1
    }
    Add-Finding 'HEALTH_TIMEOUT' "$Label not healthy after ${TimeoutSec}s: $Url" 'blocker'
    return $false
}

function Resolve-Exe([string]$Name) {
    # NOTE: multiple matches (e.g. the real python.exe + the WindowsApps
    # stub) make $cmd an ARRAY whose .Source concatenates into an invalid
    # path; always take the first match in PATH order.
    $cmd = Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $cmd) { return $null }
    return [string]$cmd.Source
}

function Get-ToolVersion([string]$Name, [string]$ArgLine) {
    # ProcessStartInfo probe: PS 5.1 native-command stderr handling and
    # $ErrorActionPreference=Stop make `& exe args` unreliable; this reads
    # stdout/stderr and windowless-launches without involving the pipeline.
    $exe = Resolve-Exe $Name
    if (-not $exe) { return $null }
    try {
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $exe
        $psi.Arguments = $ArgLine
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.UseShellExecute = $false
        $psi.CreateNoWindow = $true
        $proc = [System.Diagnostics.Process]::Start($psi)
        $stdout = $proc.StandardOutput.ReadToEnd()
        $stderr = $proc.StandardError.ReadToEnd()
        [void]$proc.WaitForExit(15000)
        $text = $stdout
        if ([string]::IsNullOrWhiteSpace($text)) { $text = $stderr }
        if ([string]::IsNullOrWhiteSpace($text)) { return $null }
        $line = ($text -split "[`r`n]+" | Where-Object { $_.Trim() } | Select-Object -First 1)
        if ($null -eq $line) { return $null }
        return ([string]$line).Trim()
    } catch {
        return $null
    }
}

function Resolve-ModelsManifest([string]$Pkg, [string]$Explicit) {
    if (-not [string]::IsNullOrWhiteSpace($Explicit)) { return $Explicit }
    $dirs = Get-ScriptDirs
    $candidate = Join-Path $dirs.repo_root 'packaging\demo\models.json'
    if (Test-Path -LiteralPath $candidate) { return $candidate }
    $alt = Join-Path $Pkg 'packaging\demo\models.json'
    if (Test-Path -LiteralPath $alt) { return $alt }
    return $candidate
}

function Resolve-ModelsRoot([string]$Explicit, [string]$Pkg, $Manifest) {
    if (-not [string]::IsNullOrWhiteSpace($Explicit)) { return $Explicit }
    if (-not [string]::IsNullOrWhiteSpace($env:MF2D_MODELS_ROOT)) { return $env:MF2D_MODELS_ROOT }
    # Fallback: the in-tree media-workflow registry declares the engine models root.
    foreach ($candidate in @((Join-Path $Pkg 'app\media_workflows\model_profiles.json'),
                             (Join-Path $Pkg 'backend\app\media_workflows\model_profiles.json'))) {
        if (Test-Path -LiteralPath $candidate) {
            try {
                $reg = Get-Content -LiteralPath $candidate -Raw | ConvertFrom-Json
                if ($reg.engine.models_root) { return [string]$reg.engine.models_root }
            } catch { }
        }
    }
    if ($Manifest -and $Manifest.models_root) { return [string]$Manifest.models_root }
    return ''
}

function Invoke-ModelCheck([string]$ManifestPath, [string]$Root) {
    $result = @{ manifest = $ManifestPath; root = $Root; status = 'NOT_RUN'; present = @(); missing = @(); total_bytes = 0 }
    if (-not (Test-Path -LiteralPath $ManifestPath)) {
        Add-Finding 'MODELS_MANIFEST_MISSING' "models manifest not found: $ManifestPath" 'blocker'
        $result.status = 'blocked'
        return $result
    }
    $mf = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
    if ([string]::IsNullOrWhiteSpace($Root)) {
        Add-Finding 'MODELS_ROOT_UNSET' 'no models root: pass -ModelsRoot or set MF2D_MODELS_ROOT' 'blocker'
        $result.status = 'blocked'
        return $result
    }
    if (-not (Test-Path -LiteralPath $Root)) {
        Add-Finding 'MODELS_ROOT_MISSING' "models root does not exist: $Root" 'blocker'
        $result.status = 'blocked'
        return $result
    }
    foreach ($m in $mf.models) {
        $full = Join-Path $Root ($m.rel -replace '/', '\')
        $present = $false
        $size = $null
        if (Test-Path -LiteralPath $full) {
            $item = Get-Item -LiteralPath $full
            if ($item.Length -gt 0) { $present = $true; $size = $item.Length }
        }
        if ($present) {
            $result.present += @{ id = [string]$m.id; rel = [string]$m.rel; bytes = [int64]$size; expected_bytes = [int64]$m.bytes }
            $result.total_bytes = [int64]$result.total_bytes + [int64]$size
        } else {
            $result.missing += @{ id = [string]$m.id; rel = [string]$m.rel; expected_bytes = [int64]$m.bytes }
            Add-Finding 'MODEL_MISSING' ("{0} ({1}) missing under {2}" -f $m.id, $m.rel, $Root) 'blocker'
        }
    }
    if ($result.missing.Count -gt 0) { $result.status = 'blocked' } else { $result.status = 'ok' }
    return $result
}

function Get-ProcIdentity([int]$ProcId) {
    try {
        $p = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcId" -ErrorAction Stop
        if (-not $p) { return $null }
        return @{
            pid = [int]$p.ProcessId
            creation_time = ([datetime]$p.CreationDate).ToUniversalTime().ToString('o')
            executable = [string]$p.ExecutablePath
            command = [string]$p.CommandLine
        }
    } catch {
        return $null
    }
}

function Test-IdentityMatch($Recorded, $Live) {
    if (-not $Live) { return @{ ok = $false; why = 'process not alive / not probeable' } }
    if ([int]$Live.pid -ne [int]$Recorded.pid) { return @{ ok = $false; why = 'pid mismatch' } }
    $rec = [string]$Recorded.creation_time
    $live = [string]$Live.creation_time
    if ([string]::IsNullOrWhiteSpace($rec)) { return @{ ok = $false; why = 'recorded creation time missing' } }
    $tr = [datetime]::Parse($rec).ToUniversalTime()
    $tl = [datetime]::Parse($live).ToUniversalTime()
    if ([math]::Abs(($tr - $tl).TotalSeconds) -gt 2.0) {
        return @{ ok = $false; why = "creation-time mismatch (PID reused): recorded $rec live $live" }
    }
    return @{ ok = $true; why = 'identity verified' }
}

function Get-StatePath([string]$Rt) { return (Join-Path $Rt 'launcher_state.json') }

function Read-State([string]$Rt) {
    $sp = Get-StatePath $Rt
    if (-not (Test-Path -LiteralPath $sp)) { return $null }
    try { return (Get-Content -LiteralPath $sp -Raw | ConvertFrom-Json) } catch { return $null }
}

function Write-State([string]$Rt, $State) {
    if (-not (Test-Path -LiteralPath $Rt)) { [void](New-Item -ItemType Directory -Path $Rt -Force) }
    $sp = Get-StatePath $Rt
    # $State may be a hashtable OR a PSCustomObject (from ConvertFrom-Json);
    # ConvertTo-Json handles both, so no type constraint here.
    $json = $State | ConvertTo-Json -Depth 8
    # No BOM: keeps the file readable by any JSON consumer (python etc.).
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($sp, $json, $utf8)
    return $sp
}

# --- action implementations ------------------------------------------------

function Invoke-Check($Layout, [int]$BPort, [int]$FPort, [string]$ModelsManifestPath, [string]$ModelsRootPath) {
    Add-Finding 'PACKAGE' ("layout={0} root={1}" -f $Layout.layout, $Layout.package_root) 'info'
    if ($Layout.layout -eq 'staged') {
        if (-not $Layout.manifest) {
            Add-Finding 'MANIFEST_MISSING_OR_INVALID' "manifest.json missing/unparseable in $($Layout.package_root)" 'blocker'
        } elseif ($Layout.manifest.schema -ne 's12-t06a-package/2') {
            Add-Finding 'MANIFEST_SCHEMA' ("unexpected manifest schema: {0}" -f $Layout.manifest.schema) 'blocker'
        }
    } else {
        foreach ($f in @('app\main.py', 'pyproject.toml')) {
            if (-not (Test-Path -LiteralPath (Join-Path $Layout.package_root $f))) {
                Add-Finding 'PACKAGE_FILE_MISSING' "$f missing under $($Layout.package_root) [repo layout]" 'blocker'
            }
        }
    }
    foreach ($f in @('frontend\package.json')) {
        if (-not (Test-Path -LiteralPath (Join-Path $Layout.package_root $f))) {
            Add-Finding 'PACKAGE_FILE_MISSING' "$f missing under $($Layout.package_root)" 'blocker'
        }
    }

    $ports = @{ backend = $BPort; frontend = $FPort; backend_open = (Test-PortOpen $BPort); frontend_open = (Test-PortOpen $FPort) }
    if ($ports.backend_open) { Add-Finding 'PORT_IN_USE' "backend port $BPort already open on 127.0.0.1" 'blocker' }
    if ($ports.frontend_open) { Add-Finding 'PORT_IN_USE' "frontend port $FPort already open on 127.0.0.1" 'blocker' }

    $tools = @{
        python = Get-ToolVersion 'python' '--version'
        node = Get-ToolVersion 'node' '--version'
        ffmpeg = Get-ToolVersion 'ffmpeg' '-hide_banner -version'
    }
    foreach ($k in @('python', 'node', 'ffmpeg')) {
        if (-not $tools[$k]) {
            Add-Finding 'TOOL_MISSING' "$k not found on PATH (declared external runtime)" 'blocker'
        }
    }

    $modelCheck = Invoke-ModelCheck -ManifestPath $ModelsManifestPath -Root $ModelsRootPath

    $blockers = @($script:Findings | Where-Object { $_.level -eq 'blocker' })
    $status = 'ok'
    if ($blockers.Count -gt 0) { $status = 'blocked' }
    return @{
        status = $status
        layout = $Layout.layout
        package_root = $Layout.package_root
        ports = $ports
        toolchain = $tools
        models = $modelCheck
        findings = $script:Findings
    }
}

function Get-Defaults($Layout) {
    $b = $BackendPort
    $f = $FrontendPort
    if ($Layout.manifest -and $Layout.manifest.endpoint) {
        if ($b -le 0 -and $Layout.manifest.endpoint.backend_port) { $b = [int]$Layout.manifest.endpoint.backend_port }
        if ($f -le 0 -and $Layout.manifest.endpoint.frontend_port) { $f = [int]$Layout.manifest.endpoint.frontend_port }
    }
    if ($b -le 0) { $b = 8421 }
    if ($f -le 0) { $f = 3121 }
    return @{ backend = $b; frontend = $f }
}

function Start-Stack($Layout, $Ports, [string]$Rt, [string]$ModelsManifestPath, [string]$ModelsRootPath) {
    $check = Invoke-Check $Layout $Ports.backend $Ports.frontend $ModelsManifestPath $ModelsRootPath
    if ($check.status -ne 'ok') {
        Emit-Json @{ schema = $script:Schema; action = 'start'; status = 'blocked'; check = $check }
        return 3
    }
    if (-not (Test-Path -LiteralPath $Rt)) { [void](New-Item -ItemType Directory -Path $Rt -Force) }
    $logs = Join-Path $Rt 'logs'
    if (-not (Test-Path -LiteralPath $logs)) { [void](New-Item -ItemType Directory -Path $logs -Force) }
    foreach ($d in @('data', 'artifacts', 'output')) {
        $p = Join-Path $Rt $d
        if (-not (Test-Path -LiteralPath $p)) { [void](New-Item -ItemType Directory -Path $p -Force) }
    }

    $py = (Get-Command python).Source
    $node = (Get-Command node).Source
    $backendLog = Join-Path $logs 'backend.log'
    $backendErr = Join-Path $logs 'backend.err.log'
    $frontendLog = Join-Path $logs 'frontend.log'
    $frontendErr = Join-Path $logs 'frontend.err.log'

    $oldRoot = $env:MOTIONFORGE_ROOT; $oldDb = $env:MOTIONFORGE_DATABASE_URL
    $oldQa = $env:MOTIONFORGE_QA_MODE; $oldCors = $env:MOTIONFORGE_CORS_ORIGINS
    $oldPort = $env:PORT; $oldApi = $env:NEXT_PUBLIC_API_URL
    try {
        $env:MOTIONFORGE_ROOT = $Rt
        $env:MOTIONFORGE_DATABASE_URL = 'sqlite:///' + ((Join-Path $Rt 'data\motionforge.db') -replace '\\', '/')
        $env:MOTIONFORGE_QA_MODE = '1'
        $env:MOTIONFORGE_CORS_ORIGINS = "http://localhost:$($Ports.frontend),http://127.0.0.1:$($Ports.frontend)"
        $backend = Start-Process -FilePath $py -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$($Ports.backend)", '--log-level', 'warning') -WorkingDirectory $Layout.backend_dir -WindowStyle Hidden -PassThru -RedirectStandardOutput $backendLog -RedirectStandardError $backendErr
        $env:PORT = "$($Ports.frontend)"
        $env:NEXT_PUBLIC_API_URL = "http://127.0.0.1:$($Ports.backend)"
        $frontend = Start-Process -FilePath $node -ArgumentList @('node_modules/next/dist/bin/next', 'start', '-p', "$($Ports.frontend)") -WorkingDirectory $Layout.frontend_dir -WindowStyle Hidden -PassThru -RedirectStandardOutput $frontendLog -RedirectStandardError $frontendErr
    } finally {
        $env:MOTIONFORGE_ROOT = $oldRoot; $env:MOTIONFORGE_DATABASE_URL = $oldDb
        $env:MOTIONFORGE_QA_MODE = $oldQa; $env:MOTIONFORGE_CORS_ORIGINS = $oldCors
        $env:PORT = $oldPort; $env:NEXT_PUBLIC_API_URL = $oldApi
    }

    $healthUrl = "http://127.0.0.1:$($Ports.backend)/health"
    $frontUrl = "http://127.0.0.1:$($Ports.frontend)/"
    $backendUp = Wait-Http -Url $healthUrl -TimeoutSec $HealthTimeoutSec -Label 'backend'
    $frontendUp = $false
    if ($backendUp) {
        $frontendUp = Wait-Http -Url $frontUrl -TimeoutSec $HealthTimeoutSec -Label 'frontend'
    }

    $backendIdent = Get-ProcIdentity ([int]$backend.Id)
    $frontendIdent = Get-ProcIdentity ([int]$frontend.Id)
    # creation_time MUST come from the live WMI probe (the process's real
    # creation instant), never from the wall clock at record time — otherwise
    # the identity guard refuses to stop our own processes (measured: ~5 s
    # drift = health-wait time).
    $backendCreation = $null
    $frontendCreation = $null
    if ($backendIdent) { $backendCreation = $backendIdent.creation_time }
    if ($frontendIdent) { $frontendCreation = $frontendIdent.creation_time }
    $state = @{
        schema = $script:Schema
        package_root = $Layout.package_root
        layout = $Layout.layout
        runtime_root = $Rt
        backend_port = $Ports.backend
        frontend_port = $Ports.frontend
        backend_proc = @{ pid = [int]$backend.Id; creation_time = $backendCreation; identity = $backendIdent; hidden = $true }
        frontend_proc = @{ pid = [int]$frontend.Id; creation_time = $frontendCreation; identity = $frontendIdent; hidden = $true }
        started_at_utc = (Get-Date).ToUniversalTime().ToString('o')
    }
    $statePath = Write-State $Rt $state

    if (-not ($backendUp -and $frontendUp)) {
        foreach ($pidToStop in @([int]$frontend.Id, [int]$backend.Id)) {
            Stop-Process -Id $pidToStop -Force -ErrorAction SilentlyContinue
        }
        Emit-Json @{ schema = $script:Schema; action = 'start'; status = 'not_run'; health = @{ backend = $backendUp; frontend = $frontendUp }; findings = $script:Findings; state_path = $statePath }
        return 3
    }
    Emit-Json @{ schema = $script:Schema; action = 'start'; status = 'ok'; backend_pid = [int]$backend.Id; frontend_pid = [int]$frontend.Id; backend_port = $Ports.backend; frontend_port = $Ports.frontend; backend_url = $healthUrl; frontend_url = $frontUrl; state_path = $statePath }
    return 0
}

function Invoke-Status($Layout, $Ports, [string]$Rt, [string]$ModelsManifestPath, [string]$ModelsRootPath) {
    $state = Read-State $Rt
    if (-not $state) {
        Emit-Json @{ schema = $script:Schema; action = 'status'; status = 'not_running'; detail = "no launcher state at $Rt" }
        return 0
    }
    # The state file is the source of truth for the ports actually bound —
    # status must not depend on the caller re-passing -PackageRoot.
    if ($state.backend_port -and $state.frontend_port) {
        $Ports = @{ backend = [int]$state.backend_port; frontend = [int]$state.frontend_port }
    }
    $procs = @{}
    foreach ($key in @('backend', 'frontend')) {
        $rec = $state."${key}_proc"
        if (-not $rec) { $procs[$key] = @{ pid = $null; alive = $false; identity = 'no record' }; continue }
        $live = Get-ProcIdentity ([int]$rec.pid)
        $match = Test-IdentityMatch $rec $live
        $winHandle = $null
        $aliveProc = Get-Process -Id ([int]$rec.pid) -ErrorAction SilentlyContinue
        if ($aliveProc) { $winHandle = [int64]$aliveProc.MainWindowHandle }
        $procs[$key] = @{ pid = [int]$rec.pid; alive = [bool]$match.ok; identity = $match.why; executable = $null; hidden = $true; main_window_handle = $winHandle }
        if ($live) { $procs[$key].executable = $live.executable }
    }
    $health = @{
        backend = Test-HttpOk -Url "http://127.0.0.1:$($Ports.backend)/health" -TimeoutSec 5
        frontend = Test-HttpOk -Url "http://127.0.0.1:$($Ports.frontend)/" -TimeoutSec 5
    }
    $modelCheck = Invoke-ModelCheck -ManifestPath $ModelsManifestPath -Root $ModelsRootPath
    $status = 'ok'
    if (-not ($health.backend -and $health.frontend)) { $status = 'degraded' }
    $blockers = @($script:Findings | Where-Object { $_.level -eq 'blocker' })
    if ($blockers.Count -gt 0 -and $status -eq 'ok') { $status = 'degraded' }
    Emit-Json @{ schema = $script:Schema; action = 'status'; status = $status; package_root = [string]$state.package_root; runtime_root = $Rt; ports = @{ backend = $Ports.backend; frontend = $Ports.frontend }; processes = $procs; health = $health; models = $modelCheck; findings = $script:Findings }
    if ($status -eq 'ok') { return 0 }
    return 3
}

function Invoke-Stop([string]$Rt, $Ports) {
    $state = Read-State $Rt
    if (-not $state) {
        Emit-Json @{ schema = $script:Schema; action = 'stop'; status = 'not_running'; detail = "no launcher state at $Rt" }
        return 0
    }
    $results = @{}
    $refused = $false
    foreach ($key in @('frontend', 'backend')) {
        $rec = $state."${key}_proc"
        if (-not $rec -or -not $rec.pid) { $results[$key] = @{ status = 'no_record' }; continue }
        $live = Get-ProcIdentity ([int]$rec.pid)
        if (-not $live) {
            $results[$key] = @{ pid = [int]$rec.pid; status = 'already_gone' }
            continue
        }
        $match = Test-IdentityMatch $rec $live
        if (-not $match.ok) {
            $refused = $true
            $results[$key] = @{ pid = [int]$rec.pid; status = 'refused'; why = $match.why }
            continue
        }
        Stop-Process -Id ([int]$rec.pid) -Force
        $deadline = (Get-Date).AddSeconds(20)
        while ((Get-Date) -lt $deadline) {
            if (-not (Get-ProcIdentity ([int]$rec.pid))) { break }
            Start-Sleep -Milliseconds 300
        }
        $gone = -not (Get-ProcIdentity ([int]$rec.pid))
        $results[$key] = @{ pid = [int]$rec.pid; status = 'stopped'; verified_gone = $gone }
    }
    if (-not $refused) {
        $updated = New-Object System.Collections.Hashtable
        foreach ($p in $state.PSObject.Properties) { $updated[$p.Name] = $p.Value }
        $updated['stopped_at_utc'] = (Get-Date).ToUniversalTime().ToString('o')
        [void](Write-State $Rt $updated)
    }
    $status = 'stopped'
    if ($refused) { $status = 'refused_identity_mismatch' }
    Emit-Json @{ schema = $script:Schema; action = 'stop'; status = $status; results = $results; state_path = (Get-StatePath $Rt) }
    if ($refused) { return 3 }
    return 0
}

# --- main ------------------------------------------------------------------

try {
    $pkg = Resolve-PackageRoot $PackageRoot
    $rt = Resolve-RuntimeRoot $RuntimeRoot
    $layout = Get-LayoutInfo $pkg
    $ports = Get-Defaults $layout
    $mm = Resolve-ModelsManifest $pkg $ModelsManifest
    $mr = Resolve-ModelsRoot $ModelsRoot $pkg $layout.manifest

    $code = 0
    switch ($Action) {
        'check' {
            $check = Invoke-Check $layout $ports.backend $ports.frontend $mm $mr
            Emit-Json @{ schema = $script:Schema; action = 'check'; status = $check.status; layout = $check.layout; package_root = $check.package_root; ports = $check.ports; toolchain = $check.toolchain; models = $check.models; findings = $check.findings }
            if ($check.status -ne 'ok') { $code = 3 }
        }
        'start' {
            $code = Start-Stack $layout $ports $rt $mm $mr
        }
        'status' {
            $code = Invoke-Status $layout $ports $rt $mm $mr
        }
        'stop' {
            $code = Invoke-Stop $rt $ports
        }
    }
    exit $code
} catch {
    Add-Finding 'LAUNCHER_ERROR' ([string]$_.Exception.Message) 'blocker'
    Emit-Json @{ schema = $script:Schema; action = $Action; status = 'blocked'; findings = $script:Findings }
    exit 3
}
