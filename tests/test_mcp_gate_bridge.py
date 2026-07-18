"""Adversarial contract for the fail-closed MCP gate bridge tombstone."""
from __future__ import annotations

import sys

from maworld_core import mcp_gate_bridge as bridge


P = F = 0


def ok(name: str, condition: bool) -> None:
    global P, F
    passed = bool(condition)
    P += int(passed)
    F += int(not passed)
    print(("  PASS " if passed else "  FAIL ") + name)


def refused(*args: object, **kwargs: object) -> bool:
    try:
        bridge.activate(*args, **kwargs)
    except bridge.BridgeDisabled:
        return True
    return False


ok("bridge status is explicit", bridge.STATUS == "PENDING_REWIRE")
ok("live effects are disabled", bridge.LIVE_EFFECTS_ALLOWED is False)
ok("plain activation is refused", refused())
ok("caller boolean cannot enable bridge", refused(enabled=True, owner_approved=True))

callback_called = False


def legacy_signer(*_args: object, **_kwargs: object) -> str:
    global callback_called
    callback_called = True
    return "forged"


ok("legacy signer injection is refused", refused(sign_approval=legacy_signer))
ok("legacy signer is never invoked", not callback_called)
ok("removed signing API is not exported", not hasattr(bridge, "sign_approval"))

bridge.LIVE_EFFECTS_ALLOWED = True
ok("mutable module flag still cannot bypass tombstone", refused(enabled=True))

print(f"\nTALLY mcp-gate-bridge: PASS={P} FAIL={F}")
sys.exit(1 if F else 0)
