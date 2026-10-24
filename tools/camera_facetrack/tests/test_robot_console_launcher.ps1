# Offline launcher checks: no real processes, listeners, COM ports or services.
$ErrorActionPreference = 'Stop'
$launcher = Join-Path (Split-Path $PSScriptRoot -Parent) 'robot-console.ps1'
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($launcher, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
foreach ($definition in $ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst]}, $false)) {
    . ([scriptblock]::Create($definition.Extent.Text))
}
function Assert($Condition, $Message) { if (!$Condition) { throw $Message } }
$temporaryRoot = Join-Path ([IO.Path]::GetTempPath()) ('robot-launcher-test-' + [guid]::NewGuid().ToString('N'))
$runtimeRoot = $temporaryRoot
$manifestPath = Join-Path $temporaryRoot 'processes.json'
New-Item -ItemType Directory -Path $temporaryRoot | Out-Null
try {
    $created = [datetime]'2026-10-24T12:00:00Z'
    $runner = Join-Path $temporaryRoot 'model-0123456789abcdef0123456789abcdef.ps1'
    $owner = [pscustomobject]@{ProcessId=101; ParentProcessId=1; CreationDate=$created; ExecutablePath='C:/fake/powershell.exe'; CommandLine="powershell -File $runner"}
    $child = [pscustomobject]@{ProcessId=102; ParentProcessId=101; CreationDate=$created.AddSeconds(1); ExecutablePath='C:/fake/python.exe'; CommandLine='python model.py'}
    $unrelated = [pscustomobject]@{ProcessId=999; ParentProcessId=1; CreationDate=$created; ExecutablePath='C:/fake/python.exe'; CommandLine='unrelated'}
    $entry = [pscustomobject]@{name='model';pid=101;createdTicks=$created.ToUniversalTime().Ticks.ToString();executable=$owner.ExecutablePath;commandLine=$owner.CommandLine;runner=$runner}
    $script:fakeProcesses = @($owner, $child, $unrelated)
    $script:stopped = @()
    function Get-CimInstance($ClassName, $Filter, $ErrorAction) {
        if ($Filter -match 'ProcessId = (\d+)') { return $script:fakeProcesses | Where-Object ProcessId -eq ([int]$Matches[1]) }
        return $script:fakeProcesses
    }
    function Stop-Process($Id, [switch]$Force, $ErrorAction) { $script:stopped += $Id }
    Save-Manifest @($entry)
    $restored = @(Read-Manifest)
    Assert ($restored.Count -eq 1 -and $restored[0].pid -eq 101) 'Manifest round trip failed'
    Assert ($null -ne (Get-OwnedProcess $entry)) 'Matching identity should be owned'
    Stop-OwnedProcess $entry
    Assert (($script:stopped -join ',') -eq '102,101') 'Stop must only terminate descendants then owner'
    $script:stopped = @()
    $owner.CreationDate = $created.AddMinutes(1)
    Stop-OwnedProcess $entry
    Assert ($script:stopped.Count -eq 0) 'Reused PID was incorrectly stopped'
    $owner.CreationDate = $created
    $owner.CommandLine = 'powershell unrelated.ps1'
    Assert ($null -eq (Get-OwnedProcess $entry)) 'Different command should not be owned'
    function Invoke-WebRequest($Uri, [switch]$UseBasicParsing, $TimeoutSec) {
        return [pscustomobject]@{StatusCode=200; Content=$script:fakeHttp}
    }
    $script:fakeHttp = '{"ready":false,"model":"LLaMA-Omni2-0.5B-Bilingual","sampleRate":24000}'
    Assert (!(Test-Service @{name='model'; url='http://fake/health'})) 'Unready model must fail health'
    $script:fakeHttp = '{"ready":true,"model":"LLaMA-Omni2-0.5B-Bilingual","sampleRate":24000}'
    Assert (Test-Service @{name='model'; url='http://fake/health'}) 'Ready model must pass health'
    $script:fakeHttp = '{"connected":false,"revision":0}'
    Assert (Test-Service @{name='device'; url='http://fake/status'}) 'Device API may be ready while board connects'
    $script:fakeHttp = '<html>unrelated server</html>'
    Assert (!(Test-Service @{name='web'; url='http://fake/'})) 'Unrelated HTTP listener must not count as Vite'
    Assert ((Quote-PsLiteral "a'b") -eq "'a''b'") 'Literal shell quoting failed'
    $consoleRoot = Split-Path $PSScriptRoot -Parent
    $Config = Join-Path $consoleRoot 'robot-console.example.json'
    $settings = Read-ConsoleConfig
    Assert ($settings.features.camera -and $settings.features.faceVoice -and !$settings.features.workbench) 'Native speech must default on and optional workbench off'
    $ViAgentRoot = 'C:/fake/vi-agent'
    $ModelPython = 'C:/fake/python.exe'
    $modelRoot = 'C:/fake/model'
    $Port = 'COM15'
    $ModelTimeoutSeconds = 180
    $web = @(Get-Services | Where-Object name -eq 'web')[0]
    Assert ($web.environment.VI_NATIVE_ONLY -eq 'true') 'Default web must only show native speech'
    $settings.features.workbench = $true
    $web = @(Get-Services | Where-Object name -eq 'web')[0]
    Assert ($web.environment.VI_NATIVE_ONLY -eq 'false') 'Explicit workbench mode must retain existing UI'
    $settings.features.workbench = $false
    $invalid = Join-Path $temporaryRoot 'invalid.json'
    $settings.features.camera = $false
    $settings | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $invalid
    $Config = $invalid
    $rejected = $false
    try { Read-ConsoleConfig | Out-Null } catch { $rejected = $true }
    Assert $rejected 'faceVoice without camera must be rejected'
    function Start-Process($FilePath, $ArgumentList, $WorkingDirectory, $WindowStyle, [switch]$PassThru, $RedirectStandardOutput, $RedirectStandardError) {
        Assert ($WindowStyle -eq 'Hidden') 'Background runner must be hidden'
        $script:fakeProcesses += [pscustomobject]@{ProcessId=103; ParentProcessId=1; CreationDate=[datetime]::UtcNow; ExecutablePath=$FilePath; CommandLine=($FilePath + ' ' + ($ArgumentList -join ' '))}
        return [pscustomobject]@{Id=103}
    }
    $started = Start-OwnedProcess @{name='device'; directory=$temporaryRoot; executable='C:/fake/python.exe'; arguments=@('a path/app.py', '--headless'); environment=@{WTCC_ROBOT_API_PORT=8791}}
    Assert ($null -ne (Get-OwnedProcess $started)) 'Started process identity was not recorded'
    $generated = Get-Content -LiteralPath $started.runner -Raw
    Assert ($generated.Contains('$env:WTCC_ROBOT_API_PORT = ''8791''')) 'Child environment was not isolated into runner'
    Assert ($generated.Contains("'a path/app.py' '--headless'")) 'Arguments with spaces were not quoted'
    Assert ($generated.Contains('exit $LASTEXITCODE')) 'Runner does not preserve native exit status'
    $runnerErrors = $null
    [Management.Automation.Language.Parser]::ParseFile($started.runner, [ref]$tokens, [ref]$runnerErrors) | Out-Null
    Assert (!$runnerErrors.Count) 'Generated runner has invalid syntax'
    Write-Host 'PASS launcher syntax, manifest, ownership/PID reuse, bounded tree cleanup and health checks.'
} finally {
    $resolved = [IO.Path]::GetFullPath($temporaryRoot)
    if (!(Split-Path $resolved -Leaf).StartsWith('robot-launcher-test-')) { throw 'Unexpected test cleanup path' }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}
