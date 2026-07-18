"""Read-only status tombstone for the retired external dialectic self-audit.

This file is not a security attestation and deliberately does not repeat the
historical PASS/VERIFIED claims.  It imports no project outside this directory,
reads no live state, and writes no report.
"""
from __future__ import annotations

import json


STATUS = "BLOCKED"
REASON = (
    "legacy self-audit depended on an unpinned external Python import and "
    "writable runtime; no trustworthy adjudication evidence was produced"
)


def report() -> dict:
    """Return static, non-authoritative status without inspecting the machine."""
    return {
        "status": STATUS,
        "scope": "legacy_external_dialectic_integration",
        "authoritative": False,
        "external_import_attempted": False,
        "live_state_read": False,
        "report_written": False,
        "reason": REASON,
    }


def main() -> int:
    print(json.dumps(report(), sort_keys=True))
    # A blocked audit must not look like a successful verification to scripts.
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
