"""Deprecated Operator Cockpit v0 entry point -- hard-disabled.

The original module exposed unsigned local JSON through an unauthenticated
network server.  It is intentionally unable to start any HTTP service.  Use a
future cockpit integration built around a fixed ActionVerifier and a fixed
EvidenceAcceptor; unsigned JSON is never operational evidence.
"""
from __future__ import annotations

import sys


HTTP_DISABLED_REASON = (
    "Operator Cockpit v0 is disabled until canonical ActionVerifier and "
    "EvidenceAcceptor integration is installed"
)


def load_state() -> dict:
    """Return only the fail-closed status; v0 no longer loads evidence files."""

    return {
        "disabled": True,
        "truth": "UNVERIFIED/PROPOSED",
        "systems": [],
        "audit": None,
        "errors": [HTTP_DISABLED_REASON],
    }


def main() -> int:
    print(HTTP_DISABLED_REASON, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
