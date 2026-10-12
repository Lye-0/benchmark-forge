param([switch]$Torch, [switch]$Sandbox)
. "$PSScriptRoot/common.ps1"
Push-Location (Join-Path $PSScriptRoot '..')
try {
    $doctorArgs = @('run', '--no-sync', 'forge', 'doctor')
    if ($Torch) { $doctorArgs += '--torch' }
    Invoke-Checked uv $doctorArgs
    if ($Sandbox) { Invoke-Checked uv @('run', '--no-sync', 'forge', 'sandbox-check') }
} finally { Pop-Location }
