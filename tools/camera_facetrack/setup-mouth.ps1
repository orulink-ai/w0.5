$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv-mouth/Scripts/python.exe'
if (!(Test-Path -LiteralPath $python)) {
    if (Get-Command uv -ErrorAction SilentlyContinue) { uv venv --python 3.12 .venv-mouth }
    else { py -3.12 -m venv .venv-mouth }
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create optional mouth tracking environment.' }
}
if (Get-Command uv -ErrorAction SilentlyContinue) {
    uv pip install --python $python -r requirements-mouth.lock.txt
} else {
    & $python -m pip install -r requirements-mouth.lock.txt
}
if ($LASTEXITCODE -ne 0) { throw 'Mouth tracking dependencies failed to install.' }
& $python face_engine.py
if ($LASTEXITCODE -ne 0) { throw 'Face detector setup failed.' }
& $python mouth_tracking.py
if ($LASTEXITCODE -ne 0) { throw 'Mouth model download/check failed.' }
Write-Host 'Ready. Set cameraPython in runtime/robot-console/config.json to .venv-mouth/Scripts/python.exe, restart console, then enable mouth assistance.'
