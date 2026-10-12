param([ValidateSet('base', 'transformers', 'transformers-cuda')][string]$Backend = 'base')
. "$PSScriptRoot/common.ps1"
Push-Location (Join-Path $PSScriptRoot '..')
try {
    Get-Command uv -ErrorAction Stop | Out-Null
    Get-Command npm.cmd -ErrorAction Stop | Out-Null
    $syncArgs = @('sync', '--locked', '--python', '3.12')
    if ($Backend -ne 'base') { $syncArgs += @('--extra', $Backend) }
    Invoke-Checked uv $syncArgs
    Invoke-Checked npm.cmd @('--prefix', 'apps/web', 'ci', '--no-audit', '--no-fund')
    Invoke-Checked npm.cmd @('--prefix', 'apps/web', 'run', 'build')
    Write-Host 'Ready. Run .\scripts\start.ps1 (Ctrl+C to stop).'
} finally { Pop-Location }
