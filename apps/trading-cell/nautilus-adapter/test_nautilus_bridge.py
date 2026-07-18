import hashlib
import hmac
import inspect
import uuid

from nautilus_bridge import (
    NautilusRiskGate,
    RiskSnapshot,
    RiskSnapshotIssuer,
    RiskSnapshotVerifier,
)


P = F = 0


def ok(name, condition, detail=""):
    global P, F
    passed = bool(condition)
    P += passed
    F += not passed
    print(("PASS | " if passed else "FAIL | ") + name + ("" if passed else f" <- {detail}"))


NOW = 1_700_000_000
KEY = b"nautilus-observer-test-key"


def sign(message: bytes) -> str:
    return hmac.new(KEY, message, hashlib.sha256).hexdigest()


def verify(message: bytes, signature: str) -> bool:
    return hmac.compare_digest(sign(message), signature)


trusted = {"risk-observer": verify}
verifier = RiskSnapshotVerifier(trusted, clock=lambda: NOW)
issuer = RiskSnapshotIssuer("risk-observer", sign, clock=lambda: NOW)
gate = NautilusRiskGate(verifier)


def snapshot(reconciliation="MATCH", heartbeat="HEALTHY", trades=0, *, now=NOW, ttl=30):
    return issuer.issue(
        reconciliation_state=reconciliation,
        heartbeat_state=heartbeat,
        trades_today=trades,
        ttl_s=ttl,
        now=now,
    )


def order(observation=None, **overrides):
    values = {
        "client_order_id": str(uuid.uuid4()),
        "instrument": "BTCUSDT",
        "side": "BUY",
        "qty_fixed": 1_000_000,
        "proposed_risk_bps": 50,
        "snapshot": observation,
    }
    values.update(overrides)
    return gate.on_order(**values)


r = order(snapshot())
ok("verified healthy observation yields eligibility only", r["gate"] == "ELIGIBLE_PROPOSAL")
ok("eligible result never submits or claims authority",
   r["submitted"] is False and r["authoritative"] is False and r["status"] == "PROPOSED")
ok("proposal preserves exact order intent", r["intent"]["qty_fixed"] == 1_000_000 and r["intent"]["side"] == "BUY")
ok("proposal names the external authority/effect boundary", "Action Authority" in r["requires"])

r = order()
ok("missing observation fails closed", r["gate"] == "INELIGIBLE_PROPOSAL" and "MALFORMED" in r["reason"])
r = order({"reconciled": True, "heartbeat_ok": True})
ok("caller booleans are not accepted as evidence", r["gate"] == "INELIGIBLE_PROPOSAL" and "MALFORMED" in r["reason"])
params = inspect.signature(NautilusRiskGate.on_order).parameters
ok("order API exposes no reconciled/heartbeat authority booleans",
   "reconciled" not in params and "heartbeat_ok" not in params)
try:
    order(snapshot(), reconciled=True, heartbeat_ok=True); old_bool_api = True
except TypeError:
    old_bool_api = False
ok("legacy true-default authority API is gone", not old_bool_api)

r = order(snapshot(), proposed_risk_bps=200)
ok("over-risk proposal is ineligible", r["gate"] == "INELIGIBLE_PROPOSAL" and r["reason"] == "RISK_PER_TRADE_EXCEEDED")
r = order(snapshot(reconciliation="MISMATCH"))
ok("signed reconciliation mismatch remains fail-closed",
   r["gate"] == "INELIGIBLE_PROPOSAL" and r["reason"] == "RECONCILIATION_NOT_VERIFIED")
r = order(snapshot(heartbeat="LOST"))
ok("heartbeat loss blocks risk-increasing proposal",
   r["gate"] == "INELIGIBLE_PROPOSAL" and r["reason"] == "HEARTBEAT_NOT_HEALTHY")
r = order(snapshot(heartbeat="LOST"), side="SELL", reduce_only=True)
ok("heartbeat loss can only produce a reduce-only proposal",
   r["gate"] == "REDUCE_ONLY_PROPOSAL" and r["intent"]["reduce_only"] is True and not r["submitted"])
r = order(snapshot(trades=20))
ok("signed daily count enforces trade cap", r["gate"] == "INELIGIBLE_PROPOSAL" and r["reason"] == "MAX_TRADES_PER_DAY")

good = snapshot()
forged = RiskSnapshot(**{**good.to_dict(), "trades_today": 0, "sig": "0" * 64})
r = order(forged)
ok("forged observation signature is rejected", r["gate"] == "INELIGIBLE_PROPOSAL" and "BAD_SIGNATURE" in r["reason"])
r = order(snapshot(now=NOW - 30, ttl=30))
ok("expired observation is rejected", r["gate"] == "INELIGIBLE_PROPOSAL" and "EXPIRED" in r["reason"])
r = order(snapshot(now=NOW + 6))
ok("future observation beyond skew is rejected", r["gate"] == "INELIGIBLE_PROPOSAL" and "FROM_FUTURE" in r["reason"])

evil_key = b"untrusted-observer-test-key"


def evil_sign(message: bytes) -> str:
    return hmac.new(evil_key, message, hashlib.sha256).hexdigest()


def evil_verify(message: bytes, signature: str) -> bool:
    return hmac.compare_digest(evil_sign(message), signature)


trusted["evil"] = evil_verify
evil_issuer = RiskSnapshotIssuer("evil", evil_sign, clock=lambda: NOW)
evil = evil_issuer.issue(
    reconciliation_state="MATCH",
    heartbeat_state="HEALTHY",
    trades_today=0,
    now=NOW,
)
r = order(evil)
ok("verifier allowlist is copied and fixed at construction",
   r["gate"] == "INELIGIBLE_PROPOSAL" and "UNTRUSTED_ISSUER" in r["reason"])

try:
    good.trades_today = 999
    frozen = False
except Exception:
    frozen = True
ok("signed observation object is immutable", frozen)
r = order(snapshot(), proposed_risk_bps=float("nan"))
ok("non-integer/NaN risk input fails closed", r["gate"] == "INELIGIBLE_PROPOSAL" and r["reason"] == "INVALID_ORDER")
try:
    NautilusRiskGate(object()); verifier_required = False
except TypeError:
    verifier_required = True
ok("gate requires the explicit verifier type", verifier_required)

print(f"\nTALLY nautilus proposal bridge: PASS={P} FAIL={F}")
raise SystemExit(1 if F else 0)
