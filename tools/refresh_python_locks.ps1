$ErrorActionPreference = "Stop"

$Uv = (Get-Command uv -ErrorAction Stop).Source
$Cutoff = "2026-07-16T00:00:00Z"
$Common = @(
    "--universal",
    "--python-version", "3.10",
    "--only-binary", ":all:",
    "--generate-hashes",
    "--exclude-newer", $Cutoff,
    "--no-sources",
    "--no-python-downloads",
    "--no-cache",
    "--no-progress"
)

function Invoke-LockCompile {
    param(
        [Parameter(Mandatory = $true)][string[]]$Sources,
        [Parameter(Mandatory = $true)][string]$Output,
        [string[]]$ExtraArgs = @()
    )
    & $Uv -q pip compile @Sources @ExtraArgs @Common --output-file $Output
    if ($LASTEXITCODE -ne 0) {
        throw "uv lock generation failed for $Output"
    }
}

Invoke-LockCompile -Sources @("pyproject.toml") -Output "requirements/default.lock.txt"
Invoke-LockCompile -Sources @("pyproject.toml") -ExtraArgs @("--extra", "trading") -Output "requirements/trading.lock.txt"
Invoke-LockCompile -Sources @("requirements/ci-verification.in") -Output "requirements/ci-verification.lock.txt"

Write-Host "Python hash locks refreshed. Run: python tools/check_supply_chain.py"
