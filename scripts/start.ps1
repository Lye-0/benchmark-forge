param([ValidateRange(1, 65535)][int]$Port = $(if ($env:FORGE_API_PORT) { [int]$env:FORGE_API_PORT } else { 8000 }))
. "$PSScriptRoot/common.ps1"
Push-Location (Join-Path $PSScriptRoot '..')
try {
    if (!(Test-Path 'apps/web/dist/index.html') -or !(Test-Path '.venv/Scripts/python.exe')) {
        throw 'Run .\scripts\setup.ps1 first.'
    }
    # No sync here: preserve the selected CPU/CUDA optional dependencies.
    Invoke-Checked uv @('run', '--no-sync', 'forge', 'serve', '--port', "$Port")
} finally { Pop-Location }
