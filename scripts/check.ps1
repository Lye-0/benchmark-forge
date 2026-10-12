. "$PSScriptRoot/common.ps1"
Push-Location (Join-Path $PSScriptRoot '..')
try {
    Invoke-Checked uv @('run', '--no-sync', 'ruff', 'check', 'src', 'tests', 'scripts')
    Invoke-Checked uv @('run', '--no-sync', 'ruff', 'format', '--check', 'src', 'tests', 'scripts')
    Invoke-Checked uv @('run', '--no-sync', 'mypy', 'src')
    Invoke-Checked uv @('run', '--no-sync', 'pytest', '-q')
    Invoke-Checked uv @('run', '--no-sync', 'python', 'scripts/secret_scan.py')
    Invoke-Checked npm.cmd @('--prefix', 'apps/web', 'run', 'test')
    Invoke-Checked npm.cmd @('--prefix', 'apps/web', 'run', 'build')
} finally { Pop-Location }
