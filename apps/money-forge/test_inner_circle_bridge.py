"""The legacy webhook bridge is deliberately non-authoritative."""

from inner_circle_bridge import event_to_evidence, process_webhook
from money_forge_gate import LEGACY_PAYMENT_DISABLED, advance


class MockVerifier:
    def __init__(self, valid=True, raises=False):
        self.valid = valid
        self.raises = raises
        self.calls = 0

    def verify_webhook(self, payload, sig_header):
        self.calls += 1
        if self.raises:
            raise RuntimeError("verifier unavailable")
        return payload if self.valid and sig_header == "good-sig" else None


checkout = {
    "type": "checkout.session.completed",
    "data": {"object": {"customer": "cus_1", "amount_total": 99700}},
}
renewal = {
    "type": "invoice.paid",
    "data": {
        "object": {
            "customer": "cus_1",
            "billing_reason": "subscription_cycle",
            "amount_paid": 99700,
        }
    },
}
subscription = {
    "type": "customer.subscription.created",
    "data": {"object": {"customer": "cus_1"}},
}

good = MockVerifier()
R = {
    "checkout event emits no legacy evidence": event_to_evidence(checkout) is None,
    "renewal event emits no legacy evidence": event_to_evidence(renewal) is None,
    "subscription.created emits no legacy evidence": event_to_evidence(subscription) is None,
    "verified transport is not promoted to proof": process_webhook(good, checkout, "good-sig") is None,
    "transport verifier was still invoked": good.calls == 1,
    "bad signature emits no evidence": process_webhook(good, checkout, "forged-sig") is None,
    "verifier failure stays fail-closed": process_webhook(
        MockVerifier(raises=True), checkout, "good-sig"
    ) is None,
}

boundary = advance("DISTRIBUTION_TEST", "PAYMENT_TEST", [])
R["absence of proof cannot cross legacy gate"] = (
    boundary.decision == "DENY" and boundary.reason == LEGACY_PAYMENT_DISABLED
)

print("== Money Forge legacy Stripe bridge (disabled) ==")
ok = True
for name, passed in R.items():
    print(("PASS" if passed else "FAIL"), "|", name)
    ok = ok and passed
print("\n" + (f"ALL PASS ({sum(R.values())}/{len(R)})" if ok else "FAIL"))

import sys

sys.exit(0 if ok else 1)
