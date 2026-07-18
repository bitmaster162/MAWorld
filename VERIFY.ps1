[CmdletBinding()]
param([switch]$SkipRust)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONDONTWRITEBYTECODE = "1"

function Invoke-CheckedPython {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
    & python @Args
    if ($LASTEXITCODE -ne 0) {
        throw "python command failed ($LASTEXITCODE): $($Args -join ' ')"
    }
}

Write-Host "== MAWorld self-verify =="
Invoke-CheckedPython tests/run_all.py
Invoke-CheckedPython tools/check_supply_chain.py
Invoke-CheckedPython tools/audit_python_locks_osv.py
Invoke-CheckedPython libs/maworld_core/check_single_source.py
Invoke-CheckedPython tests/run_active_entrypoints.py
Push-Location services/sandbox-broker
try {
    Invoke-CheckedPython tier2_acceptance.py
} finally {
    Pop-Location
}
if ($SkipRust) {
    Write-Warning "Rust verification explicitly skipped; this is not full local evidence."
} else {
    & (Join-Path $PSScriptRoot "tools/verify_rust.ps1")
}
Write-Host "== Local checks complete; SKIP is not production evidence =="
