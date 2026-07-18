#!/usr/bin/env sh
set -eu

AUDIT_VERSION="0.22.2"
AUDIT_SHA256="7fb9497f8594b389e5fce5ef9b92db08432996895b2e0c5a0167a69ed445c428"
ADVISORY_DB_COMMIT="b5fc89b8be99e96f79194d8a6f11e9b4143b99f0"
LOCKFILE="${1:-Cargo.lock}"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT INT TERM

test -f "$LOCKFILE"
cargo fetch --locked --quiet

ASSET="$WORK_DIR/cargo-audit.tgz"
curl --fail --location --silent --show-error \
  "https://github.com/rustsec/rustsec/releases/download/cargo-audit/v${AUDIT_VERSION}/cargo-audit-x86_64-unknown-linux-musl-v${AUDIT_VERSION}.tgz" \
  --output "$ASSET"
printf '%s  %s\n' "$AUDIT_SHA256" "$ASSET" | sha256sum --check
tar -xzf "$ASSET" -C "$WORK_DIR"

DB="$WORK_DIR/advisory-db"
git init --quiet "$DB"
git -C "$DB" remote add origin https://github.com/RustSec/advisory-db.git
git -C "$DB" fetch --quiet --depth 1 origin "$ADVISORY_DB_COMMIT"
git -C "$DB" checkout --quiet --detach FETCH_HEAD
test "$(git -C "$DB" rev-parse HEAD)" = "$ADVISORY_DB_COMMIT"

"$WORK_DIR/cargo-audit-x86_64-unknown-linux-musl-v${AUDIT_VERSION}/cargo-audit" audit \
  --db "$DB" \
  --no-fetch \
  --deny warnings \
  --file "$LOCKFILE"
