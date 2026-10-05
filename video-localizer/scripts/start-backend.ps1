$ErrorActionPreference = 'Stop'
$repoDir = Split-Path $PSScriptRoot -Parent
Set-Location $repoDir
$env:PYTHONPATH = Join-Path $repoDir 'backend'
& (Join-Path $repoDir '.venv/Scripts/python.exe') -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
exit $LASTEXITCODE
