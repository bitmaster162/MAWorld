"""Fail-closed adapter to the real Cedar authorization backend."""
from __future__ import annotations

from dataclasses import dataclass

try:
    import cedarpy
except ImportError:
    cedarpy = None


def cedar_backend_available() -> bool:
    return cedarpy is not None


@dataclass(frozen=True)
class CedarAuthorization:
    allowed: bool
    reason: str
    backend_available: bool


def authorize_detailed(
    principal, action, resource, policies_cedar, context=None
) -> CedarAuthorization:
    if cedarpy is None:
        return CedarAuthorization(False, "cedar backend unavailable", False)
    request = {
        "principal": principal,
        "action": action,
        "resource": resource,
        "context": context or {},
    }
    try:
        result = cedarpy.is_authorized(request, policies_cedar, [])
    except Exception as exc:
        return CedarAuthorization(
            False, "cedar evaluation error: " + type(exc).__name__, True
        )
    allowed = (
        result.decision is cedarpy.Decision.Allow and result.allowed is True
    )
    diagnostics_errors = list(getattr(result.diagnostics, "errors", []) or [])
    if diagnostics_errors:
        allowed = False
        reason = "cedar evaluation error"
    elif allowed:
        reason = "cedar allow"
    elif result.decision is cedarpy.Decision.NoDecision:
        reason = "cedar no decision"
    else:
        reason = "cedar deny"
    return CedarAuthorization(allowed, reason, True)


def authorize(principal, action, resource, policies_cedar, context=None) -> bool:
    """Compatibility boolean; backend errors/unavailability always deny."""
    return authorize_detailed(
        principal, action, resource, policies_cedar, context
    ).allowed
