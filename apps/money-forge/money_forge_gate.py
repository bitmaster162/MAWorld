"""Legacy Money Forge research-stage gate.

This module is intentionally unable to authorize PAYMENT, RETENTION, or SCALE.
The old API trusted a caller-controlled ``Evidence.verified`` boolean, so it
could not establish that a payment authority had actually signed a payment.

Use ``money_forge_v2.advance_to_payment`` for the payment boundary.  That API
requires an explicit EvidenceIssuer and EvidenceAcceptor and accepts only a
payment-authority-signed proof.
"""
from __future__ import annotations

from dataclasses import dataclass, field


STAGES = [
    "DISCOVER",
    "SCORE",
    "RESEARCH",
    "VALIDATE_PROBLEM",
    "DESIGN_EXPERIMENT",
    "PROTOTYPE",
    "DISTRIBUTION_TEST",
    "PAYMENT_TEST",
    "RETENTION_TEST",
    "SCALE",
]

_PAYMENT_BOUNDARY = STAGES.index("DISTRIBUTION_TEST")
LEGACY_PAYMENT_DISABLED = "LEGACY_PAYMENT_PATH_DISABLED_USE_MONEY_FORGE_V2"


@dataclass(frozen=True)
class Evidence:
    """A non-authoritative research signal.

    Deliberately has no ``verified`` field.  Values supplied through this
    legacy type can help order research stages, but can never prove payment.
    """

    kind: str
    source: str
    detail: dict = field(default_factory=dict)


@dataclass(frozen=True)
class GateResult:
    decision: str
    reason: str


def advance(from_stage: str, to_stage: str, evidence: list[Evidence]) -> GateResult:
    """Advance research stages only; fail closed at the economic boundary."""

    if to_stage == "KILL":
        return GateResult("KILLED", "explicit kill")
    if from_stage not in STAGES or to_stage not in STAGES:
        return GateResult("DENY", "UNKNOWN_STAGE")
    if STAGES.index(to_stage) != STAGES.index(from_stage) + 1:
        return GateResult("DENY", "NON_SEQUENTIAL")

    if STAGES.index(to_stage) > _PAYMENT_BOUNDARY:
        return GateResult("DENY", LEGACY_PAYMENT_DISABLED)

    if not evidence:
        return GateResult("DENY", "NEEDS_SOME_EVIDENCE")
    return GateResult("ADVANCE", "OK_RESEARCH_ONLY")
