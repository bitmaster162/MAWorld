"""Verifier-only Money Forge payment boundary.

The gate's EvidenceAcceptor is fixed at construction.  A caller supplies the
exact Claim previously prepared by this gate and a signed VerificationResult
from the external evidence service; it cannot choose an issuer or trust anchor
at the moment of advancement.
"""
from __future__ import annotations

from maworld_core.evidence_engine import (
    Claim,
    ClaimKind,
    EvidenceAcceptor,
    VerificationResult,
)


STAGES = [
    "DISCOVER", "SCORE", "RESEARCH", "VALIDATE", "PROTOTYPE",
    "DISTRIBUTION", "PAYMENT", "RETENTION", "SCALE",
]


class MoneyForgeGate:
    def __init__(self, evidence_acceptor: EvidenceAcceptor):
        if not isinstance(evidence_acceptor, EvidenceAcceptor):
            raise TypeError("fixed verifier-only EvidenceAcceptor required")
        self._acceptor = evidence_acceptor

    def prepare_payment_claim(self, payment: dict) -> Claim:
        if not isinstance(payment, dict):
            raise TypeError("payment statement must be a dict")
        return Claim(ClaimKind.PRODUCT_SUCCESS, dict(payment), "money-forge")

    def advance(self, claim: Claim, result: VerificationResult) -> dict:
        if (
            not isinstance(claim, Claim)
            or claim.kind != ClaimKind.PRODUCT_SUCCESS
            or claim.asserted_by != "money-forge"
        ):
            return {"advanced": False, "reason": "wrong Money Forge claim", "stage": "BLOCKED"}
        try:
            decision = self._acceptor.accept(claim, result)
        except (TypeError, ValueError):
            return {"advanced": False, "reason": "invalid evidence result", "stage": "BLOCKED"}
        return {
            "advanced": decision.accepted,
            "reason": decision.reason,
            "stage": "PAYMENT" if decision.accepted else "BLOCKED",
        }


def advance_to_payment(*_args, **_kwargs):
    """Removed per-call trust API; construct one MoneyForgeGate at composition root."""
    raise TypeError("legacy per-call evidence authority is disabled; use MoneyForgeGate")


__all__ = ["STAGES", "MoneyForgeGate", "advance_to_payment"]
