"""Fail-closed static validation for committed dependency/image pins."""
from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCK_DIR = ROOT / "requirements"
REQ_RE = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)")
HASH_RE = re.compile(r"--hash=sha256:[0-9a-f]{64}(?:\s|$)")
DIGEST_RE = re.compile(r"^\s*image:\s*[^\s]+@sha256:[0-9a-f]{64}\s*$", re.MULTILINE)
ACTION_RE = re.compile(r"^\s*- uses:\s*[^@\s]+@([^\s#]+)", re.MULTILINE)


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def direct(requirements: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for requirement in requirements:
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)(?:\[[^]]+\])?==([^;\s]+)", requirement)
        if match is None:
            raise ValueError(f"direct dependency is not exactly pinned: {requirement}")
        result[normalize(match.group(1))] = match.group(2)
    return result


def parse_lock(path: Path) -> tuple[dict[str, set[str]], int]:
    text = path.read_text(encoding="utf-8")
    if "--exclude-newer 2026-07-16T00:00:00Z" not in text:
        raise ValueError(f"{path.name}: missing audited resolution cutoff")
    if "--generate-hashes" not in text or "--only-binary :all:" not in text:
        raise ValueError(f"{path.name}: unsafe generation header")
    if re.search(r"^\s*(?:--index-url|--extra-index-url|-e\s)", text, re.MULTILINE):
        raise ValueError(f"{path.name}: embedded index/editable source forbidden")
    lines = text.splitlines()
    resolved: dict[str, set[str]] = {}
    entries = 0
    for index, line in enumerate(lines):
        match = REQ_RE.match(line)
        if match is None:
            continue
        entries += 1
        name, version = normalize(match.group(1)), match.group(2)
        end = index + 1
        while end < len(lines) and not REQ_RE.match(lines[end]):
            end += 1
        block = "\n".join(lines[index:end])
        if HASH_RE.search(block) is None:
            raise ValueError(f"{path.name}: {name} has no SHA-256 hash")
        # Universal locks may carry mutually exclusive Python/platform marker
        # branches for a transitive dependency.
        resolved.setdefault(name, set()).add(version)
    if entries == 0:
        raise ValueError(f"{path.name}: empty lock")
    return resolved, entries


def main() -> int:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    defaults = direct(project["project"]["dependencies"])
    extras = project["project"]["optional-dependencies"]
    trading = {**defaults, **direct(extras["trading"])}
    verification = direct(extras["verification"])
    profiles = {
        "default.lock.txt": defaults,
        "trading.lock.txt": trading,
        "ci-verification.lock.txt": verification,
    }
    total_entries = 0
    for filename, expected in profiles.items():
        resolved, entries = parse_lock(LOCK_DIR / filename)
        total_entries += entries
        for name, version in expected.items():
            if version not in resolved.get(name, set()):
                raise ValueError(
                    f"{filename}: expected direct pin {name}=={version}, "
                    f"found {sorted(resolved.get(name, set()))!r}"
                )
    ci_input = direct(
        [
            line.strip()
            for line in (LOCK_DIR / "ci-verification.in").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
    )
    if ci_input != verification:
        raise ValueError("ci-verification.in differs from pyproject verification extra")

    compose = (ROOT / "infrastructure" / "docker-compose.yml").read_text(encoding="utf-8")
    if len(DIGEST_RE.findall(compose)) != 3:
        raise ValueError("every compose image must be pinned to an exact SHA-256 digest")
    migration_mounts = [
        "001_intake_core_v1_1.sql:/docker-entrypoint-initdb.d/001_kf_intake.sql:ro",
        "002_rls_roles.sql:/docker-entrypoint-initdb.d/002_kf_rls_roles.sql:ro",
        "003_atomic_intake.sql:/docker-entrypoint-initdb.d/003_kf_atomic_intake.sql:ro",
        "004_authority_grants.sql:/docker-entrypoint-initdb.d/004_kf_authority_grants.sql:ro",
    ]
    migration_positions = [compose.find(mount) for mount in migration_mounts]
    if any(position < 0 for position in migration_positions) or migration_positions != sorted(
        migration_positions
    ):
        raise ValueError("Compose must mount the complete ordered KF 001/002/003/004 migration chain")
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    if "--require-hashes" not in workflow or "ci-verification.lock.txt" not in workflow:
        raise ValueError("CI does not enforce the verification hash lock")
    if "tools/audit_python_locks_osv.py" not in workflow:
        raise ValueError("CI does not audit every universal lock branch")

    rust_toolchain = tomllib.loads((ROOT / "rust-toolchain.toml").read_text(encoding="utf-8"))
    if rust_toolchain.get("toolchain", {}).get("channel") != "1.97.1":
        raise ValueError("Rust toolchain must be pinned to exact 1.97.1")
    cargo_lock = tomllib.loads((ROOT / "Cargo.lock").read_text(encoding="utf-8"))
    rust_package_rows = cargo_lock.get("package", [])
    rust_packages = {package["name"] for package in rust_package_rows}
    forbidden = {"rsa", "sqlx", "sqlx-mysql", "sqlx-sqlite"} & rust_packages
    if forbidden:
        raise ValueError(f"Rust lock contains unused/vulnerable driver surface: {sorted(forbidden)}")
    if not {"sqlx-core", "sqlx-postgres"}.issubset(rust_packages):
        raise ValueError("Rust lock is missing the direct PostgreSQL dependency pair")

    rust_workflow = (ROOT / ".github" / "workflows" / "rust.yml").read_text(
        encoding="utf-8"
    )
    if len(DIGEST_RE.findall(rust_workflow)) != 1:
        raise ValueError("Rust CI container must be pinned to one exact SHA-256 digest")
    for command in (
        "cargo fmt --all -- --check",
        "cargo test --workspace --locked",
        "cargo clippy --workspace --all-targets --all-features --locked -- -D warnings",
        "sh tools/audit_rust.sh Cargo.lock",
    ):
        if command not in rust_workflow:
            raise ValueError(f"Rust CI is missing required gate: {command}")
    trust_pin_name = "MAWORLD_KF_TRUST_REGISTRY_SHA256"
    if f"unset {trust_pin_name}" not in rust_workflow:
        raise ValueError("Rust CI must compile/test the incapable unpinned intake binary")
    for gate_path in (ROOT / "tools" / "verify_rust.ps1", ROOT / "VERIFY.sh"):
        if f"unset {trust_pin_name}" not in gate_path.read_text(encoding="utf-8"):
            raise ValueError(
                f"{gate_path.relative_to(ROOT)} must remove the intake trust pin for verification"
            )
    intake_manifest = (ROOT / "apps" / "knowledge-foundry" / "kf-intake" / "Cargo.toml").read_text(
        encoding="utf-8"
    )
    if 'ed25519-dalek = { version = "=3.0.0", default-features = false }' not in intake_manifest:
        raise ValueError("kf-intake Ed25519 verifier must be exact-pinned without default features")
    intake_authority = (
        ROOT / "apps" / "knowledge-foundry" / "kf-intake" / "src" / "authority.rs"
    ).read_text(encoding="utf-8")
    if f'option_env!("{trust_pin_name}")' not in intake_authority:
        raise ValueError("kf-intake trust registry digest must be a build-time pin")
    if re.search(rf"std::env::(?:var|var_os)\([^\n]*{trust_pin_name}", intake_authority):
        raise ValueError("kf-intake must not accept a runtime trust registry digest fallback")
    action_refs = ACTION_RE.findall(workflow) + ACTION_RE.findall(rust_workflow)
    if not action_refs or not all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in action_refs):
        raise ValueError("every CI action must use an immutable 40-hex commit pin")

    rust_audit = (ROOT / "tools" / "audit_rust.sh").read_text(encoding="utf-8")
    if not re.search(r'AUDIT_SHA256="[0-9a-f]{64}"', rust_audit):
        raise ValueError("Rust audit binary checksum is not pinned")
    if not re.search(r'ADVISORY_DB_COMMIT="[0-9a-f]{40}"', rust_audit):
        raise ValueError("RustSec advisory database commit is not pinned")

    print(f"PASS supply-chain locks: profiles={len(profiles)} entries={total_entries}")
    print("PASS compose image digests: 3/3")
    print("PASS Compose KF migration chain: 001/002/003/004")
    print("PASS CI hash and all-marker OSV enforcement")
    print(f"PASS Rust lock/toolchain/CI audit pins: packages={len(rust_package_rows)}")
    print("PASS kf-intake build-time trust pin and unpinned verification contract")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyError, OSError, TypeError, ValueError, tomllib.TOMLDecodeError) as error:
        print(f"FAIL supply-chain validation: {error}", file=sys.stderr)
        raise SystemExit(1)
