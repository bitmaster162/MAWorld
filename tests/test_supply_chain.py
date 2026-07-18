from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
P = F = 0


def ok(name, condition, detail=""):
    global P, F
    passed = bool(condition)
    P += passed
    F += not passed
    print(("  PASS " if passed else "  FAIL ") + name + ("" if passed else f" <- {detail}"))


checker = subprocess.run(
    [sys.executable, str(ROOT / "tools" / "check_supply_chain.py")],
    cwd=ROOT,
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
)
ok("committed supply-chain checker passes", checker.returncode == 0, checker.stderr[-300:])

locks = {
    name: (ROOT / "requirements" / name).read_text(encoding="utf-8")
    for name in ("default.lock.txt", "trading.lock.txt", "ci-verification.lock.txt")
}
ok("all Python profiles enforce SHA-256 hashes",
   all("--generate-hashes" in text and "--hash=sha256:" in text for text in locks.values()))
ok("all Python profiles are wheel-only resolutions",
   all("--only-binary :all:" in text for text in locks.values()))
ok("all Python profiles use the fixed audit cutoff",
   all("--exclude-newer 2026-07-16T00:00:00Z" in text for text in locks.values()))
ok("Nautilus transitive pins are resolver-compatible",
   "msgspec==0.18.6" in locks["trading.lock.txt"]
   and "fsspec==2023.6.0" in locks["trading.lock.txt"])

compose = (ROOT / "infrastructure" / "docker-compose.yml").read_text(encoding="utf-8")
ok("every compose image is immutable",
   len(re.findall(r"^\s*image:\s*[^\s]+@sha256:[0-9a-f]{64}\s*$", compose, re.MULTILINE)) == 3)
compose_migrations = [
    "001_intake_core_v1_1.sql:/docker-entrypoint-initdb.d/001_kf_intake.sql:ro",
    "002_rls_roles.sql:/docker-entrypoint-initdb.d/002_kf_rls_roles.sql:ro",
    "003_atomic_intake.sql:/docker-entrypoint-initdb.d/003_kf_atomic_intake.sql:ro",
]
compose_migration_positions = [compose.find(mount) for mount in compose_migrations]
ok("Compose initializes the complete ordered KF migration chain",
   all(position >= 0 for position in compose_migration_positions)
   and compose_migration_positions == sorted(compose_migration_positions))

workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
rust_workflow = (ROOT / ".github" / "workflows" / "rust.yml").read_text(encoding="utf-8")
ok("CI installs only the committed hash lock",
   "--require-hashes" in workflow and "--only-binary=:all:" in workflow
   and "requirements/ci-verification.lock.txt" in workflow)
ok("CI audits every universal lock marker branch",
   "tools/audit_python_locks_osv.py" in workflow)
uses = re.findall(
    r"^\s*- uses:\s*[^@\s]+@([^\s#]+)", workflow + "\n" + rust_workflow, re.MULTILINE
)
ok("CI actions are immutable commit pins",
   bool(uses) and all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in uses))

cargo_lock = (ROOT / "Cargo.lock").read_text(encoding="utf-8")
ok("Rust lock excludes unused vulnerable drivers",
   all(f'name = "{name}"' not in cargo_lock
       for name in ("rsa", "sqlx", "sqlx-mysql", "sqlx-sqlite")))
toolchain = (ROOT / "rust-toolchain.toml").read_text(encoding="utf-8")
ok("Rust toolchain is an exact point release", 'channel = "1.97.1"' in toolchain)
ok("Rust CI container is immutable",
   len(re.findall(r"^\s*image:\s*rust:[^\s]+@sha256:[0-9a-f]{64}\s*$",
                  rust_workflow, re.MULTILINE)) == 1)
ok("Rust CI runs locked test, lint, and audit gates",
   "cargo test --workspace --locked" in rust_workflow
   and "cargo clippy --workspace --all-targets --all-features --locked -- -D warnings" in rust_workflow
   and "sh tools/audit_rust.sh Cargo.lock" in rust_workflow)
rust_audit = (ROOT / "tools" / "audit_rust.sh").read_text(encoding="utf-8")
ok("RustSec tool and advisory database are immutable pins",
   re.search(r'AUDIT_SHA256="[0-9a-f]{64}"', rust_audit) is not None
   and re.search(r'ADVISORY_DB_COMMIT="[0-9a-f]{40}"', rust_audit) is not None)

print(f"\nTALLY supply-chain: PASS={P} FAIL={F}")
sys.exit(1 if F else 0)
