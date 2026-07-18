import hashlib
import hmac

import money_forge_v2 as M
import evidence_engine as E

P = F = 0


def ok(name, condition, detail=""):
    global P, F
    passed = bool(condition)
    P += passed
    F += not passed
    print(("  PASS " if passed else "  FAIL ") + name + ("" if passed else f" <- {detail}"))


def sign(key):
    return lambda message: hmac.new(key, message, hashlib.sha256).hexdigest()


def verify(key):
    return lambda message, signature: hmac.compare_digest(
        hmac.new(key, message, hashlib.sha256).hexdigest(), signature
    )


payment_key = b"money-forge-payment"
evidence_key = b"money-forge-evidence"
payment_authority = E.PaymentProofIssuer("stripe-webhook", sign(payment_key))
payment_verifier = E.PaymentProofVerifier({"stripe-webhook": verify(payment_key)})
evidence_issuer = E.EvidenceIssuer(
    "money-forge-evidence", sign(evidence_key), payment_verifier=payment_verifier
)
evidence_acceptor = E.EvidenceAcceptor({"money-forge-evidence": verify(evidence_key)})
gate = M.MoneyForgeGate(evidence_acceptor)


def advance(payment):
    claim=gate.prepare_payment_claim(payment)
    return gate.advance(claim,evidence_issuer.verify(claim))


payment_id = "pi_9"
amount = 19900
scope = {
    "tenant_id": "tenant-a", "merchant_account": "acct-main",
    "customer_id": "customer-9", "currency": "USD", "provider": "stripe",
}
good = {
    "event_type": "payment_intent.succeeded",
    "payment_id": payment_id,
    "amount_cents": amount,
    "payment_token": payment_authority.issue(
        payment_id, amount, "payment_intent.succeeded", **scope
    ),
    **scope,
}
ok("externally signed payment_intent.succeeded advances PAYMENT", advance(good)["advanced"])
ok("bare dict verified=True does not advance", not advance({"verified": True})["advanced"])

subscription = {
    "event_type": "customer.subscription.created",
    "payment_id": payment_id,
    "amount_cents": amount,
    "payment_token": payment_authority.issue(
        payment_id, amount, "customer.subscription.created", **scope
    ),
    **scope,
}
ok("subscription.created does not advance", not advance(subscription)["advanced"])

forged = {
    "event_type": "payment_intent.succeeded",
    "payment_id": payment_id,
    "amount_cents": amount,
    "payment_token": {**good["payment_token"], "sig": "forged"},
}
ok("forged token does not advance", not advance(forged)["advanced"])

try: M.advance_to_payment(good,evidence_issuer,evidence_acceptor); legacy=False
except TypeError: legacy=True
ok("legacy per-call trust API is disabled",legacy)

attacker_key=b"attacker-evidence"
attacker_issuer=E.EvidenceIssuer("attacker",sign(attacker_key),payment_verifier=payment_verifier)
attacker_claim=gate.prepare_payment_claim(good)
ok("caller-selected evidence issuer cannot replace fixed trust anchor",
   not gate.advance(attacker_claim,attacker_issuer.verify(attacker_claim))["advanced"])

other_claim=gate.prepare_payment_claim({**good,"amount_cents":1})
ok("signed result for another exact claim cannot advance",
   not gate.advance(other_claim,evidence_issuer.verify(gate.prepare_payment_claim(good)))["advanced"])

import sys
print(f"\nTALLY money-forge v2: PASS={P} FAIL={F}")
sys.exit(1 if F else 0)
