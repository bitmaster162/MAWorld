from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
P = F = 0


def read(relative_path: str) -> str:
    path = ROOT / relative_path
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def ok(name: str, condition: bool, detail: str = "") -> None:
    global P, F
    passed = bool(condition)
    P += passed
    F += not passed
    print(("  PASS " if passed else "  FAIL ") + name + ("" if passed else f" <- {detail}"))


def release_is_blocked(text: str) -> bool:
    return bool(
        re.search(r"LIVE\s*(?::|=)\s*\**OFF\**", text, re.IGNORECASE)
        and re.search(
            r"BUILD_FREEZE\s*(?::|=)\s*\**BLOCKED\**",
            text,
            re.IGNORECASE,
        )
    )


status = read("STATUS.md")
deploy = read("DEPLOY.md")
ok(
    "canonical status keeps LIVE off and the build freeze blocked",
    release_is_blocked(status),
    "STATUS.md must state LIVE=OFF and BUILD_FREEZE=BLOCKED",
)
ok(
    "deployment gate keeps LIVE off and the build freeze blocked",
    release_is_blocked(deploy),
    "DEPLOY.md must state LIVE=OFF and BUILD_FREEZE=BLOCKED",
)

kf_module = read("apps/knowledge-foundry/MODULE.md")
ok(
    "Knowledge Foundry module remains on security hold",
    "HOLD" in kf_module.upper() and "RUST_SECURITY_HOLD.md" in kf_module,
    "module must retain HOLD and point to the Rust security gate",
)

module_map = read("MODULE_MAP.md")
kf_map_lines = [
    line
    for line in module_map.splitlines()
    if any(name in line.casefold() for name in ("knowledge-foundry", "kf-intake", "kf-store-pg"))
]
ok(
    "module map does not promote Knowledge Foundry historical spikes",
    any("SECURITY HOLD" in line.upper() for line in kf_map_lines)
    and not any(re.search(r"WIP.*PASSED", line, re.IGNORECASE) for line in kf_map_lines),
    "Knowledge Foundry must be SECURITY HOLD with no stale WIP ... PASSED line",
)

trading_module = read("apps/trading-cell/MODULE.md")
ok(
    "RiskService is documented as proposal-only, not authority",
    "proposal-only" in trading_module.casefold()
    and not re.search(r"RiskService\s*[—-]\s*авторитет", trading_module, re.IGNORECASE),
    "trading MODULE must not call RiskService an authority",
)

kf_readme = read("apps/knowledge-foundry/kf-intake/README.md")
ok(
    "Knowledge Foundry README labels demo output as historical",
    "SECURITY HOLD" in kf_readme.upper()
    and "собирается и проходит acceptance" not in kf_readme.casefold(),
    "README must retain SECURITY HOLD and remove the stale acceptance claim",
)

rust_hold = read("apps/knowledge-foundry/RUST_SECURITY_HOLD.md")
ok(
    "Rust security hold separates closed local work from current blockers",
    all(
        marker in rust_hold
        for marker in (
            "Локально закрыто",
            "Остаётся HOLD",
            "SET LOCAL",
            "kf_runtime",
            "Cargo.lock",
            "RustSec",
        )
    ),
    "closed Rust evidence and remaining authority/RLS blockers must both be explicit",
)

rls_script = read("apps/knowledge-foundry/schema/rls_isolation_test.py")
ok(
    "destructive RLS acceptance retains its hard safety gates",
    'CONFIRMATION = "DROP_PUBLIC_SCHEMA_IN_DEDICATED_MAWORLD_RLS_TEST_DB"' in rls_script
    and 'CLUSTER_CONFIRMATION = "RESET_GLOBAL_KF_ROLES_IN_DISPOSABLE_POSTGRES_CLUSTER"'
    in rls_script
    and all(host in rls_script for host in ('"localhost"', '"127.0.0.1"', '"::1"'))
    and 'prefix = "maworld_rls_test_"' in rls_script
    and all(override in rls_script for override in ("hostaddr", "service", "options"))
    and "inet_server_addr()" in rls_script
    and "actual_database != expected_database" in rls_script
    and "server_ip = ipaddress.ip_interface(server_address).ip" in rls_script
    and "if not server_ip.is_loopback" in rls_script
    and "pg_is_in_recovery()" in rls_script
    and "other_user_databases" in rls_script
    and all(name in rls_script for name in ("template0", "template1", "postgres"))
    and "datallowconn" not in rls_script
    and "datistemplate" not in rls_script
    and "sys.argv" not in rls_script
    and "psycopg2" not in rls_script.casefold(),
    "confirmation, DSN override bans, actual loopback/database proof, and env-only psycopg3 are required",
)

rls_wrapper_path = ROOT / "apps/knowledge-foundry/schema/test_rls_acceptance.py"
rls_wrapper = read("apps/knowledge-foundry/schema/test_rls_acceptance.py")
ok(
    "active inventory exposes the external RLS acceptance as an explicit skip",
    rls_wrapper_path.is_file()
    and "SKIP" in rls_wrapper
    and "SystemExit(0)" in rls_wrapper
    and "from rls_isolation_test import main" in rls_wrapper,
    "active wrapper must report SKIP when dedicated PostgreSQL is unavailable",
)

historical_runbook = read("docs/27_DEPLOY_RUNBOOK.md")[:1200].upper()
ok(
    "legacy deploy runbook is visibly superseded",
    "HISTORICAL" in historical_runbook and "SUPERSEDED" in historical_runbook,
    "docs/27 must carry a HISTORICAL / SUPERSEDED banner near the top",
)

current_report = read("docs/45_SECURITY_CONTINUATION_2026-07-18.md")
ok(
    "current continuation report keeps the release blocked",
    release_is_blocked(current_report)
    and re.search(r"production\s*(?::|=)?\s*\**HOLD", current_report, re.IGNORECASE),
    "docs/45 must be the current HOLD verdict",
)

historical_docs = [
    "docs/08_ROUND4_RESULT.md",
    "docs/09_ROUND5_RESULT.md",
    "docs/10_ROUND6_RESULT.md",
    "docs/11_DR2_GAP_BYPASS_MATRIX.md",
    "docs/12_ROUND7_RESULT.md",
    "docs/13_ROUND8_RESULT.md",
    "docs/15_LIFEOS_RESEARCH_ADDENDUM.md",
    "docs/17_DR2_CONTROL_SPINE_RESULT.md",
    "docs/18_CANONICAL_SYNTHESIS_V1_5.md",
    "docs/24_FINAL_AUDIT.md",
    "docs/35_SYSTEM_WALK_AND_GAPS.md",
    "docs/37_ARENA_SPEC.md",
    "docs/40_TRACK_DECISION_AND_WEDGE.md",
    "docs/41_HERMES_LIVE_GUIDES_MATRIX.md",
    "docs/43_INCIDENT_HERMES_GATEWAY.md",
]
ok(
    "dangerous historical claims carry a uniform non-operative banner",
    all(
        all(marker in read(path)[:1600].upper() for marker in ("HISTORICAL", "SUPERSEDED", "NON-OPERATIVE"))
        for path in historical_docs
    ),
    "every listed historical audit/runbook must carry all three warning markers near the top",
)

live_runbooks = "\n".join(
    read(path)
    for path in (
        "docs/37_ARENA_SPEC.md",
        "docs/40_TRACK_DECISION_AND_WEDGE.md",
        "docs/41_HERMES_LIVE_GUIDES_MATRIX.md",
        "docs/43_INCIDENT_HERMES_GATEWAY.md",
    )
)
ok(
    "historical live runbooks contain no executable live/key-loading commands",
    "--live" not in live_runbooks
    and not re.search(r"(?:export|config\s+set)[^\n]*(?:KEY|key)", live_runbooks),
    "remove live flags and credential-loading commands rather than relying on a banner",
)

synthesis = read("docs/18_CANONICAL_SYNTHESIS_V1_5.md")
ok(
    "historical synthesis no longer advertises a ready build freeze",
    "BUILD_FREEZE_V2_READY" not in synthesis and "CORE_V4_STABLE" not in synthesis,
    "ready/stable passport must remain revoked",
)

print(f"\nTALLY release-status: PASS={P} FAIL={F}")
sys.exit(1 if F else 0)
