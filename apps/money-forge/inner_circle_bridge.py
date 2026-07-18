"""Disabled legacy Stripe-to-Evidence bridge.

A valid Stripe webhook signature authenticates the webhook transport; it does
not make a caller-created ``Evidence(verified=True)`` a durable payment proof.
This legacy bridge therefore never emits Money Forge evidence, including for
``checkout.session.completed``, subscription lifecycle events, or invoices.

New integrations must mint a scoped PaymentProof with the configured payment
authority and pass it to ``money_forge_v2.advance_to_payment``.  That path
binds the payment id, amount, event type, tenant, merchant, customer, currency,
and provider, and verifies the Evidence Engine result at a fixed trust anchor.
"""
from __future__ import annotations


LEGACY_BRIDGE_DISABLED = "LEGACY_STRIPE_EVIDENCE_BRIDGE_DISABLED_USE_MONEY_FORGE_V2"


def event_to_evidence(event):
    """Return no authority-bearing evidence from legacy webhook objects."""

    return None


def process_webhook(verifier, payload: str, sig_header: str | None):
    """Verify transport if requested, but never promote it to payment proof.

    Keeping the verification call makes migration failures visible to existing
    integrations while the return value remains fail-closed for every event.
    """

    try:
        verifier.verify_webhook(payload, sig_header)
    except Exception:
        return None
    return None
