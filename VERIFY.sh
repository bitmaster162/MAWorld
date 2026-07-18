#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "== MAWorld full local self-verify =="
python3 tests/run_all.py
python3 tools/check_supply_chain.py
python3 tools/audit_python_locks_osv.py
python3 libs/maworld_core/check_single_source.py
python3 tests/run_active_entrypoints.py
(cd services/sandbox-broker && python3 tier2_acceptance.py)

IMAGE="rust:1.97.1-bookworm@sha256:389c1ae98c20fbcadca68a685482749267cec3c90893ae4671c5a37cc894c416"
docker run --rm --platform linux/amd64 \
  -e CARGO_TARGET_DIR=/tmp/maworld-target \
  -v "${ROOT}:/work" -w /work "$IMAGE" sh -c '
    unset MAWORLD_KF_TRUST_REGISTRY_SHA256
    cargo fmt --all -- --check
    cargo test --workspace --locked
    cargo clippy --workspace --all-targets --all-features --locked -- -D warnings
    sh tools/audit_rust.sh Cargo.lock
  '

echo "== Local checks complete; SKIP is not production evidence =="
