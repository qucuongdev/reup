$ErrorActionPreference = 'Stop'
$repoPath = Split-Path $PSScriptRoot -Parent
$backendPython = Join-Path $repoPath '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $backendPython)) {
    Write-Error 'Missing .venv. Follow native setup in README.md.'
}
Push-Location (Join-Path $repoPath 'backend')
try {
    & $backendPython -m app.smoke --check
    exit $LASTEXITCODE
} finally { Pop-Location }
