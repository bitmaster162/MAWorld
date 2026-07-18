"""Fail-closed tombstone for the not-yet-rewired MCP gate bridge.

The historical bridge targeted the removed ``sign_approval`` API. Nothing in
this module can authorize an effect or construct a receipt. A future bridge
must be implemented against ``ApprovalProofIssuer`` and independently accepted
before this tombstone is replaced.
"""
from __future__ import annotations


STATUS = "PENDING_REWIRE"
LIVE_EFFECTS_ALLOWED = False


class BridgeDisabled(RuntimeError):
    """Raised for every attempted activation of the historical bridge."""


def activate(*_args: object, **_kwargs: object) -> None:
    """Refuse activation regardless of caller-provided flags or callbacks."""
    raise BridgeDisabled(
        "MCP gate bridge is disabled pending ApprovalProofIssuer rewire and acceptance"
    )


__all__ = ["BridgeDisabled", "LIVE_EFFECTS_ALLOWED", "STATUS", "activate"]
