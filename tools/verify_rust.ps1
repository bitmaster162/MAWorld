[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$Workspace = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$Image = "rust:1.97.1-bookworm@sha256:389c1ae98c20fbcadca68a685482749267cec3c90893ae4671c5a37cc894c416"
$Gate = @'
set -eu
unset MAWORLD_KF_TRUST_REGISTRY_SHA256
cargo fmt --all -- --check
cargo test --workspace --locked
cargo clippy --workspace --all-targets --all-features --locked -- -D warnings
sh tools/audit_rust.sh Cargo.lock
'@

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker is required for the pinned Rust verification gate."
}

Write-Host "== MAWorld pinned Rust verification =="
& docker run --rm --platform linux/amd64 `
    -e CARGO_TARGET_DIR=/tmp/maworld-target `
    -v "${Workspace}:/work" `
    -w /work `
    $Image sh -c $Gate

if ($LASTEXITCODE -ne 0) {
    throw "Pinned Rust verification failed ($LASTEXITCODE)."
}

Write-Host "== Rust formatting, tests, clippy, and RustSec audit are green =="
