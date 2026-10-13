"""Exercise real Windows PowerShell control flow with a deterministic uv fixture."""

import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell integration")
@pytest.mark.parametrize("mode,expected", [("missing", 1), ("verified", 0), ("broken", 1)])
def test_expected_sandbox_unavailability_preserves_exit_without_stack(mode, expected):
    script = Path(__file__).parents[1] / "scripts" / "diagnose.ps1"
    path = str(script).replace("'", "''")
    payload = {
        "missing": '{"available":false,"state":"not_installed","reason":"fixture"}',
        "verified": '{"available":true,"state":"verified"}',
        "broken": "invalid-json-fixture",
    }[mode]
    code = 0 if mode == "verified" else 1
    command = f"""
function global:uv {{
    if ($args[-1] -eq 'sandbox-check') {{
        Write-Output '{payload}'
        $global:LASTEXITCODE = {code}
    }} else {{
        Write-Output '{{"os":"Windows"}}'
        $global:LASTEXITCODE = 0
    }}
}}
$before = (Get-Location).Path
& '{path}' -Sandbox
$diagnosticExit = $LASTEXITCODE
if ((Get-Location).Path -ne $before) {{ throw 'Location was not restored' }}
exit $diagnosticExit
"""
    process = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        timeout=30,
    )
    assert process.returncode == expected
    if mode == "missing":
        assert b'"not_installed"' in process.stdout
        assert b"regular Ollama benchmarks remain available" in process.stdout
        assert not process.stderr
    elif mode == "broken":
        assert process.stderr
    else:
        assert b'"available":true' in process.stdout
        assert not process.stderr
