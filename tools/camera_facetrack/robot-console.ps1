[CmdletBinding()]
param(
    [ValidateSet('Start', 'Status', 'Stop', 'Restart', 'Logs')][string]$Action = 'Start',
    [string]$Config = '',
    [string]$Port = '',
    [string]$ViAgentRoot = '',
    [string]$ModelPython = '',
    [ValidateRange(30, 600)][int]$ModelTimeoutSeconds = 180,
    [switch]$OpenBrowser,
    [ValidateRange(1, 200)][int]$Tail = 40
)

$ErrorActionPreference = 'Stop'
$consoleRoot = $PSScriptRoot
$workspaceRoot = Split-Path (Split-Path (Split-Path $consoleRoot -Parent) -Parent) -Parent
$runtimeRoot = Join-Path $consoleRoot 'runtime/robot-console'
$manifestPath = Join-Path $runtimeRoot 'processes.json'

function Resolve-ConsolePath([string]$Value) {
    if ([IO.Path]::IsPathRooted($Value)) { return [IO.Path]::GetFullPath($Value) }
    return [IO.Path]::GetFullPath((Join-Path $consoleRoot $Value))
}

function Read-ConsoleConfig {
    if (!$Config) {
        $private = Join-Path $runtimeRoot 'config.json'
        $Config = if (Test-Path -LiteralPath $private) { $private } else { Join-Path $consoleRoot 'robot-console.example.json' }
    }
    $settings = Get-Content -LiteralPath $Config -Raw | ConvertFrom-Json
    $allowed = @('pipeline', 'viAgentRoot', 'modelRoot', 'matchaRoot', 'whisperRoot', 'cameraPython', 'modelPython', 'serialPort', 'features', 'ports')
    foreach ($property in $settings.PSObject.Properties.Name) {
        if ($property -notin $allowed) { throw "Unsupported config field '$property'. Keep all API keys in vi-agent/.env, never in this JSON." }
    }
    foreach ($feature in @('camera', 'faceVoice', 'workbench')) {
        if ($settings.features.$feature -isnot [bool]) { throw "features.$feature must be true or false" }
    }
    if ($settings.features.faceVoice -and !$settings.features.camera) { throw 'faceVoice requires camera=true for mandatory face gating' }
    $used = @()
    foreach ($name in @('model', 'device', 'web', 'api')) {
        $value = $settings.ports.$name
        if (($value -isnot [int] -and $value -isnot [long]) -or $value -lt 1024 -or $value -gt 65535 -or $value -in $used) { throw "ports.$name must be a distinct integer in 1024..65535" }
        $used += $value
    }
    if (!$settings.serialPort -or $settings.serialPort -notmatch '^COM[1-9][0-9]*$') { throw 'serialPort must be a Windows COM port such as COM15' }
    if ($settings.pipeline -and $settings.pipeline -notin @('local-s2s', 'local-cascade')) { throw 'Unsupported pipeline' }
    if ($settings.pipeline -eq 'local-cascade' -and !$settings.features.workbench) { throw 'Local cascade requires workbench=true for tools and memory' }
    return $settings
}

function Read-Manifest {
    if (!(Test-Path -LiteralPath $manifestPath)) { return @() }
    $data = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    if ($data.version -ne 1) { throw 'Unsupported robot-console manifest; refusing process management.' }
    return @($data.processes)
}

function Save-Manifest($Entries) {
    $temporary = $manifestPath + '.tmp'
    @{ version = 1; processes = @($Entries) } | ConvertTo-Json -Depth 6 |
        Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $manifestPath -Force
}

function Get-OwnedProcess($Entry) {
    $runnerPath = [IO.Path]::GetFullPath([string]$Entry.runner)
    if ((Split-Path $runnerPath -Parent) -ne $runtimeRoot -or
        (Split-Path $runnerPath -Leaf) -notmatch '^(model|device|api|web)-[a-f0-9]{32}\.ps1$') { return $null }
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $([int]$Entry.pid)" -ErrorAction SilentlyContinue
    if (!$process) { return $null }
    # PID reuse, a changed executable or a different command must never be killed.
    $created = ([datetime]$process.CreationDate).ToUniversalTime().Ticks.ToString()
    if ($created -ne [string]$Entry.createdTicks -or
        $process.ExecutablePath -ne $Entry.executable -or
        $process.CommandLine -ne $Entry.commandLine -or
        !$process.CommandLine.Contains([string]$Entry.runner)) { return $null }
    return $process
}

function Stop-OwnedProcess($Entry) {
    $owner = Get-OwnedProcess $Entry
    if (!$owner) { Write-Host "$($Entry.name): absent or ownership changed; not stopped."; return }
    $snapshot = @(Get-CimInstance Win32_Process)
    $tree = [System.Collections.Generic.List[object]]::new()
    $tree.Add($owner)
    for ($index = 0; $index -lt $tree.Count; $index++) {
        $ancestor = $tree[$index]
        foreach ($child in $snapshot) {
            if ($child.ParentProcessId -eq $ancestor.ProcessId -and
                $child.CreationDate -ge $ancestor.CreationDate -and
                !($tree.ProcessId -contains $child.ProcessId)) { $tree.Add($child) }
        }
    }
    # Recheck every process identity immediately before stopping its recorded tree.
    for ($index = $tree.Count - 1; $index -ge 0; $index--) {
        $record = $tree[$index]
        $current = Get-CimInstance Win32_Process -Filter "ProcessId = $($record.ProcessId)" -ErrorAction SilentlyContinue
        if ($current -and $current.CreationDate -eq $record.CreationDate -and
            $current.ExecutablePath -eq $record.ExecutablePath -and
            $current.CommandLine -eq $record.CommandLine) {
            Stop-Process -Id $current.ProcessId -Force -ErrorAction SilentlyContinue
        }
    }
    Write-Host "$($Entry.name): stopped owned process tree."
}

function Test-Listener([int]$ServicePort) {
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $pending = $client.ConnectAsync('127.0.0.1', $ServicePort)
        return ($pending.Wait(500) -and $client.Connected)
    } catch { return $false } finally { $client.Dispose() }
}

function Test-Service($Service) {
    try {
        $response = Invoke-WebRequest -Uri $Service.url -UseBasicParsing -TimeoutSec 3
        if ($response.StatusCode -ne 200) { return $false }
        switch ($Service.name) {
            'model' {
                $health = $response.Content | ConvertFrom-Json
                if ($settings.pipeline -eq 'local-cascade') { return ($health.ready -eq $true -and $health.pipeline -eq 'local-cascade' -and $health.sampleRate -eq 24000) }
                return ($health.ready -eq $true -and $health.model -eq 'LLaMA-Omni2-0.5B-Bilingual' -and $health.sampleRate -eq 24000)
            }
            'device' { return ($null -ne ($response.Content | ConvertFrom-Json).revision) }
            'web' { return ($response.Content -match '/@vite/client') }
            'api' {
                $health = $response.Content | ConvertFrom-Json
                return ($health.status -eq 'ok')
            }
        }
    } catch { return $false }
    return $false
}

function Quote-PsLiteral([string]$Value) { return "'" + $Value.Replace("'", "''") + "'" }

function Start-OwnedProcess($Service) {
    $identifier = [guid]::NewGuid().ToString('N')
    $runner = Join-Path $runtimeRoot "$($Service.name)-$identifier.ps1"
    $stdout = Join-Path $runtimeRoot "$($Service.name)-$identifier.stdout.log"
    $stderr = Join-Path $runtimeRoot "$($Service.name)-$identifier.stderr.log"
    $arguments = @($Service.arguments | ForEach-Object { Quote-PsLiteral ([string]$_) }) -join ' '
    $lines = @('$ErrorActionPreference = ''Stop''', '$env:PYTHONUNBUFFERED = ''1''',
        ('Set-Location -LiteralPath ' + (Quote-PsLiteral $Service.directory)))
    foreach ($key in $Service.environment.Keys) {
        $lines += '$env:' + $key + ' = ' + (Quote-PsLiteral ([string]$Service.environment[$key]))
    }
    $lines += ('& ' + (Quote-PsLiteral $Service.executable) + ' ' + $arguments)
    $lines += 'exit $LASTEXITCODE'
    $lines | Set-Content -LiteralPath $runner -Encoding UTF8
    $shell = Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0/powershell.exe'
    $process = Start-Process -FilePath $shell -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $runner + '"')) `
        -WorkingDirectory $Service.directory -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    $identity = Get-CimInstance Win32_Process -Filter "ProcessId = $($process.Id)"
    if (!$identity) { throw "$($Service.name) exited before its ownership could be recorded; see $stderr" }
    return [pscustomobject]@{ name = $Service.name; pid = $process.Id; runner = $runner
        createdTicks = ([datetime]$identity.CreationDate).ToUniversalTime().Ticks.ToString()
        executable = $identity.ExecutablePath; commandLine = $identity.CommandLine
        stdout = $stdout; stderr = $stderr }
}

function Wait-Service($Service, $Entry) {
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $nextProgress = 0
    while ($watch.Elapsed.TotalSeconds -lt $Service.timeout) {
        if (Test-Service $Service) { Write-Host "$($Service.name): ready ($($Service.url))"; return }
        if ($Entry -and !(Get-OwnedProcess $Entry)) {
            throw "$($Service.name) exited; inspect $($Entry.stderr) and $($Entry.stdout)"
        }
        if ($watch.Elapsed.TotalSeconds -ge $nextProgress) {
            Write-Host "$($Service.name): waiting $([int]$watch.Elapsed.TotalSeconds)/$($Service.timeout)s; logs: $runtimeRoot"
            $nextProgress += 10
        }
        Start-Sleep -Milliseconds 1000
    }
    throw "$($Service.name) did not become healthy at $($Service.url) within $($Service.timeout)s. Existing services were not killed. Logs: $runtimeRoot"
}

function Get-Services {
    $cameraPython = Resolve-ConsolePath $settings.cameraPython
    $npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
    $npm = if ($npmCommand) { $npmCommand.Source } else { 'npm.cmd' }
    $cameraArguments = @((Join-Path $consoleRoot 'app.py'), '--headless', '--source', "serial://$Port")
    if ($settings.features.camera) { $cameraArguments += '--autostart' }
    if ($settings.features.faceVoice) { $cameraArguments += '--voice' }
    $sharedEnvironment = @{WTCC_VI_AGENT_ROOT=$ViAgentRoot; VI_LOCAL_S2S_URL="http://127.0.0.1:$($settings.ports.model)"}
    $apiEnvironment = @{VI_VOICE_API_PORT=$settings.ports.api}
    $modelArguments = @((Join-Path $ViAgentRoot 'packages/vi-agent/scripts/llama-omni2-service.py'), '--source-root', $modelRoot, '--matcha-root', (Resolve-ConsolePath $settings.matchaRoot), '--whisper-root', (Resolve-ConsolePath $settings.whisperRoot), '--port', $settings.ports.model)
    if ($settings.pipeline -eq 'local-cascade') {
        $modelArguments = @((Join-Path $ViAgentRoot 'packages/vi-agent/scripts/local-cascade-service.py'), '--models', $modelRoot, '--port', $settings.ports.model)
        $localEnvironment = @{VI_VOICE_PROVIDER='local-cascade'; VI_VOICE_LLM_MODEL='vi-robot-local'; VI_VOICE_LLM_BASE_URL='http://127.0.0.1:11434/v1'; VI_VOICE_CWD=$ViAgentRoot; PI_CODING_AGENT_DIR=(Join-Path $ViAgentRoot '.local-cascade/pi'); VI_WORKBENCH_DATA_DIR=(Join-Path $ViAgentRoot '.local-cascade/workbench')}
        $apiEnvironment += $localEnvironment
        $sharedEnvironment += $localEnvironment
        $sharedEnvironment['VI_VOICE_API_ORIGIN'] = "http://127.0.0.1:$($settings.ports.api)"
    }
    return @(
        @{ name = 'model'; port = $settings.ports.model; url = "http://127.0.0.1:$($settings.ports.model)/health"; timeout = $ModelTimeoutSeconds; optional = $false; enabled = $settings.features.faceVoice
           executable = $ModelPython; directory = $ViAgentRoot
           environment = @{}; arguments = $modelArguments },
        @{ name = 'device'; port = $settings.ports.device; url = "http://127.0.0.1:$($settings.ports.device)/api/robot/status"; timeout = 45; optional = $false; enabled = $true
           executable = $cameraPython; directory = $consoleRoot
           environment = $sharedEnvironment + @{WTCC_ROBOT_API_PORT=$settings.ports.device}; arguments = $cameraArguments },
        @{ name = 'api'; port = $settings.ports.api; url = "http://127.0.0.1:$($settings.ports.api)/api/health"; timeout = 45; optional = ($settings.pipeline -ne 'local-cascade'); enabled = $settings.features.workbench
           executable = $npm; directory = $ViAgentRoot; environment = $apiEnvironment
           arguments = @('run', 'vi:voice:api') },
        @{ name = 'web'; port = $settings.ports.web; url = "http://127.0.0.1:$($settings.ports.web)/"; timeout = 45; optional = $false; enabled = $true
           executable = $npm; directory = $ViAgentRoot
           environment = @{VI_NATIVE_ONLY=(!$settings.features.workbench).ToString().ToLowerInvariant(); VI_ROBOT_API_ORIGIN="http://127.0.0.1:$($settings.ports.device)"; VI_VOICE_API_ORIGIN="http://127.0.0.1:$($settings.ports.api)"}
           arguments = @('run', 'vi:voice:web', '--', '--', '--strictPort', '--port', $settings.ports.web) }
    )
}

# A held file handle prevents two launchers from racing on ports or the manifest.
New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
$lock = $null
try {
    $lock = [IO.File]::Open((Join-Path $runtimeRoot 'lifecycle.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    $entries = @(Read-Manifest)
    if ($Action -eq 'Logs') {
        $logs = @(Get-ChildItem -LiteralPath $runtimeRoot -File | Where-Object Name -Match '^(model|device|api|web)-[a-f0-9]{32}\.(stdout|stderr)\.log$' | Sort-Object LastWriteTime -Descending | Select-Object -First 8)
        foreach ($log in $logs) {
                    Write-Host "--- $($log.Name) (last $Tail lines) ---"
                    Get-Content -LiteralPath $log.FullName -Tail $Tail | ForEach-Object {
                        # Defense in depth for provider errors that might echo a credential.
                        $_ -replace '(?i)(sk-|Bearer\s+)[A-Za-z0-9_.-]+', '$1[REDACTED]' -replace '(?i)((?:api[_-]?key|access[_-]?token|secret)\s*[=:]\s*)\S+', '$1[REDACTED]'
                    }
        }
        return
    }
    if ($Action -in @('Stop', 'Restart')) {
        foreach ($entry in @($entries | Sort-Object { @{web=0; device=1; model=2; api=3}[$_.name] })) { Stop-OwnedProcess $entry }
        $entries = @()
        Save-Manifest $entries
        if ($Action -eq 'Stop') { return }
    }
    $settings = Read-ConsoleConfig
    if (!$ViAgentRoot) { $ViAgentRoot = Resolve-ConsolePath $settings.viAgentRoot } else { $ViAgentRoot = Resolve-ConsolePath $ViAgentRoot }
    $modelRoot = Resolve-ConsolePath $settings.modelRoot
    if (!$ModelPython) { $ModelPython = if ($settings.modelPython) { Resolve-ConsolePath $settings.modelPython } else { Join-Path $modelRoot '.venv/Scripts/python.exe' } } else { $ModelPython = Resolve-ConsolePath $ModelPython }
    if (!$Port) { $Port = $settings.serialPort }
    if ($Port -notmatch '^COM[1-9][0-9]*$') { throw 'Port must be a COM port such as COM15' }
    $services = @(Get-Services | Sort-Object { @{model=0; api=1; device=2; web=3}[$_.name] })
    if ($Action -eq 'Status') {
        foreach ($service in $services) {
            $entry = @($entries | Where-Object { $_.name -eq $service.name -and (Get-OwnedProcess $_) })
            $ownership = if ($entry.Count) { 'owned' } else { 'external/unmanaged' }
            $health = if (Test-Service $service) { 'ready' } elseif (Test-Listener $service.port) { 'occupied, not ready' } else { 'offline' }
            Write-Host "$($service.name): $health; $ownership; enabled=$($service.enabled); $($service.url)"
        }
        Write-Host "Manifest and logs: $runtimeRoot"
        return
    }
    if ($settings.pipeline -eq 'local-cascade') {
        $tags = Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5
        if ('vi-robot-local:latest' -notin @($tags.models.name)) { throw 'Run vi-agent setup-local-cascade.ps1 first; Ollama model vi-robot-local is missing.' }
        Write-Host 'Ollama: warming local model before enabling face conversations.'
        $null = Invoke-RestMethod 'http://127.0.0.1:11434/api/generate' -Method Post -ContentType 'application/json' -Body '{"model":"vi-robot-local","stream":false,"keep_alive":"30m"}' -TimeoutSec 90
    }
    $newEntries = @()
    try {
        foreach ($service in $services) {
            if (!$service.enabled) { Write-Host "$($service.name): disabled by feature configuration."; continue }
            $entry = $null
            try {
            if (Test-Listener $service.port) {
                Write-Host "$($service.name): reusing listener on $($service.port); no process takeover."
                Wait-Service $service $null
                continue
            }
            if (!$service.executable -or !(Test-Path -LiteralPath $service.executable)) { throw "Missing runtime for $($service.name). Configure its executable path; no installation or model download is automatic." }
            if (!(Test-Path -LiteralPath $service.directory)) { throw "Missing project: $($service.directory)" }
            $entry = Start-OwnedProcess $service
            $newEntries += $entry
            $entries += $entry
            Save-Manifest $entries
            Wait-Service $service $entry
            } catch {
                if (!$service.optional) { throw }
                if ($entry) {
                    Stop-OwnedProcess $entry
                    $entries = @($entries | Where-Object runner -ne $entry.runner)
                    $newEntries = @($newEntries | Where-Object runner -ne $entry.runner)
                    Save-Manifest $entries
                }
                Write-Warning "$($service.name) unavailable: $($_.Exception.Message). Native speech and camera remain available; optional workbench is not required."
            }
        }
    } catch {
        foreach ($entry in @($newEntries | Sort-Object { @{web=0; device=1; model=2; api=3}[$_.name] })) { Stop-OwnedProcess $entry }
        $entries = @($entries | Where-Object { $_.runner -notin $newEntries.runner })
        Save-Manifest $entries
        throw
    }
    $webUrl = "http://127.0.0.1:$($settings.ports.web)/"
    Write-Host "Robot console: $webUrl (volume 80; speech requires a stable face)."
    if ($OpenBrowser) { Start-Process $webUrl }
} finally {
    if ($lock) { $lock.Dispose() }
}
