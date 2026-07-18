#!/usr/bin/env python3
"""Disabled legacy external-dialectic launcher.

The old tool mutated ``sys.path`` to a stale absolute directory and executed an
external Python module inside the audit process.  That is not a reproducible or
trusted security boundary.  Historical prose remains in docs/42, explicitly
labelled as historical, while the current audit is docs/44.
"""
from __future__ import annotations

import json


def main() -> int:
    print(json.dumps({
        "status": "BLOCKED",
        "reason": "external dialectic execution is disabled",
        "authority": False,
        "current_audit": "docs/44_SECURITY_HARDENING_2026-07-16.md",
    }, sort_keys=True))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
