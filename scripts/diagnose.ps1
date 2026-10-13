param([switch]$Torch, [switch]$Sandbox, [switch]$Gpu)
. "$PSScriptRoot/common.ps1"
Push-Location (Join-Path $PSScriptRoot '..')
try {
    $doctorArgs = @('run', '--no-sync', 'forge', 'doctor')
    if ($Gpu) { $doctorArgs += '--gpu' }
    if ($Torch) { $doctorArgs += '--torch' }
    Invoke-Checked uv $doctorArgs
    if ($Sandbox) {
        $sandboxOutput = & uv run --no-sync forge sandbox-check
        $sandboxExitCode = $LASTEXITCODE
        $sandboxOutput | Write-Output
        if ($sandboxExitCode -eq 1) {
            # Exit 1 plus a structured unavailable result is an expected diagnostic.
            # Preserve the nonzero exit code for automation without a misleading stack trace.
            $sandboxResult = ($sandboxOutput -join [Environment]::NewLine) | ConvertFrom-Json -ErrorAction Stop
            if ($sandboxResult.available -is [bool] -and $sandboxResult.available -eq $false) {
                Write-Host 'Code evaluation is unavailable; regular Ollama benchmarks remain available.'
                exit 1
            }
        }
        if ($sandboxExitCode -ne 0) { throw "Sandbox diagnostic failed with exit code $sandboxExitCode" }
    }
} finally { Pop-Location }
