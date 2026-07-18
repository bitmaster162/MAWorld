from __future__ import annotations

import hashlib
import hmac
import sys
import time
from dataclasses import replace

from compound_attestation import (
    PLATFORM_CLAIM_DOMAIN,
    AttestationChainVerifier,
    AttestationResultIssuer,
    EnrollmentIssuer,
    PlatformBindingIssuer,
    QuoteVerificationIssuer,
    SecretReleaseSubject,
    SecretReleaseVerifier,
    ar_digest,
    authorize_secret_release,
    issue_attestation_result,
    secret_release_ok,
    verify_chain,
)
from bitemporal_memory import (
    BitemporalFact,
    BitemporalStore,
    GovernancePromotionIssuer,
    GovernancePromotionVerifier,
)
from spiffe_identity import SVIDIssuer,SVIDVerifier,mint_svid,valid_svid


P = F = 0


def ok(name, condition, detail=""):
    global P, F
    passed = bool(condition)
    P += passed
    F += not passed
    print(("  PASS " if passed else "  FAIL ") + name + ("" if passed else f" <- {detail}"))


def crypto(key: bytes):
    def sign(message: bytes) -> str:
        return hmac.new(key, message, hashlib.sha256).hexdigest()

    def verify(message: bytes, signature: str) -> bool:
        expected = hmac.new(key, message, hashlib.sha256).hexdigest()
        return isinstance(signature, str) and hmac.compare_digest(signature, expected)

    return sign, verify


NOW = 1_700_000_000
ar_sign, ar_verify = crypto(b"test-only-ar-key")
_, wrong_ar_verify = crypto(b"wrong-test-only-ar-key")
ar_issuer = AttestationResultIssuer("ar-verifier", ar_sign, clock=lambda: NOW)
chain_verifier = AttestationChainVerifier(
    {"ar-verifier": ar_verify},
    allowed_capability_digests={"cap-A"},
    clock=lambda: NOW,
)

# Compound attestation: valid chain, explicit roles, immutable policy.
S = "sess-1"
ar0 = ar_issuer.issue(S, 0, "orchestrator", "m0", "ROOT", "cap-A", "req0")
ar1 = ar_issuer.issue(S, 1, "specialist", "m1", ar_digest(ar0), "cap-A", "req1")
ar2 = ar_issuer.issue(S, 2, "tool", "m2", ar_digest(ar1), "cap-A", "req2")
chain = [ar0, ar1, ar2]
ok("valid signed AR chain accepted", chain_verifier.verify(chain, S)["accepted"])
ok("serialized signed AR chain accepted", chain_verifier.verify([item.to_dict() for item in chain], S)["accepted"])
ok("explicit verifier works through compatibility helper", verify_chain(chain, S, verifier=chain_verifier)["accepted"])
ok("implicit chain verifier is fail-closed", not verify_chain(chain, S)["accepted"])

try:
    issue_attestation_result(S, 0, "a", "m", "ROOT", "cap-A", "req")
    legacy_issue_rejected = False
except RuntimeError:
    legacy_issue_rejected = True
ok("legacy result issuance requires explicit issuer", legacy_issue_rejected)
explicit_helper_ar = issue_attestation_result(
    S, 0, "a", "m", "ROOT", "cap-A", "req", issuer=ar_issuer
)
ok("compatibility issue helper accepts explicit issuer only", chain_verifier.verify([explicit_helper_ar], S)["accepted"])

# Splice, order, scope, complete-payload, trust, and lifetime falsifications.
old = ar_issuer.issue("sess-OLD", 0, "a", "m", "ROOT", "cap-A", "r")
bad_parent = ar_issuer.issue(S, 1, "b", "m", ar_digest(old), "cap-A", "r")
ok("chain splice (wrong parent) rejected", not chain_verifier.verify([ar0, bad_parent], S)["accepted"])
ok("non-monotonic/replayed hop rejected", not chain_verifier.verify([ar0, ar0], S)["accepted"])
escalated = ar_issuer.issue(S, 1, "b", "m", ar_digest(ar0), "cap-ADMIN", "r")
ok("capability scope escalation rejected", not chain_verifier.verify([ar0, escalated], S)["accepted"])
ok(
    "caller cannot widen fixed capability policy",
    not chain_verifier.verify(chain, S, delegated_scope={"cap-A", "cap-ADMIN"})["accepted"],
)
ok("empty attestation chain rejected", not chain_verifier.verify([], S)["accepted"])
ok(
    "request digest mutation invalidates full-payload signature",
    not chain_verifier.verify([ar0, replace(ar1, request_digest="req-X"), ar2], S)["accepted"],
)
ok(
    "measurement mutation invalidates full-payload signature",
    not chain_verifier.verify([replace(ar0, measurement="evil")], S)["accepted"],
)
ok(
    "expiry mutation invalidates full-payload signature",
    not chain_verifier.verify([replace(ar0, expires_at=ar0.expires_at + 1)], S)["accepted"],
)
wrong_key_verifier = AttestationChainVerifier(
    {"ar-verifier": wrong_ar_verify},
    allowed_capability_digests={"cap-A"},
    clock=lambda: NOW,
)
ok("wrong verifier key rejected", not wrong_key_verifier.verify(chain, S)["accepted"])
other_issuer = AttestationResultIssuer("unknown-verifier", ar_sign, clock=lambda: NOW)
unknown_ar = other_issuer.issue(S, 0, "a", "m", "ROOT", "cap-A", "r")
ok("issuer outside fixed allowlist rejected", not chain_verifier.verify([unknown_ar], S)["accepted"])
expired_verifier = AttestationChainVerifier(
    {"ar-verifier": ar_verify},
    allowed_capability_digests={"cap-A"},
    clock=lambda: NOW + 60,
)
ok("expired AR rejected", not expired_verifier.verify([ar0], S)["accepted"])
future_ar = ar_issuer.issue(S, 0, "a", "m", "ROOT", "cap-A", "r", now=NOW + 100)
ok("future-dated AR rejected", not chain_verifier.verify([future_ar], S)["accepted"])
short_policy = AttestationChainVerifier(
    {"ar-verifier": ar_verify},
    allowed_capability_digests={"cap-A"},
    clock=lambda: NOW,
    max_ttl_s=30,
)
ok("AR exceeding verifier TTL policy rejected", not short_policy.verify([ar0], S)["accepted"])
cross_domain_sig = ar_sign(PLATFORM_CLAIM_DOMAIN + ar0._payload())
ok(
    "cross-domain signature cannot validate as AR",
    not chain_verifier.verify([replace(ar0, sig=cross_domain_sig)], S)["accepted"],
)
mutable_ar_map = {"ar-verifier": ar_verify}
fixed_chain_verifier = AttestationChainVerifier(
    mutable_ar_map,
    allowed_capability_digests={"cap-A"},
    clock=lambda: NOW,
)
mutable_ar_map["ar-verifier"] = wrong_ar_verify
ok("chain verifier copies trust map at construction", fixed_chain_verifier.verify(chain, S)["accepted"])

# Secret release: three separately trusted, role/domain-specific signed claims.
quote_sign, quote_verify = crypto(b"test-only-quote-key")
platform_sign, platform_verify = crypto(b"test-only-platform-key")
enroll_sign, enroll_verify = crypto(b"test-only-enrollment-key")
quote_issuer = QuoteVerificationIssuer("quote-service", quote_sign, clock=lambda: NOW)
platform_issuer = PlatformBindingIssuer("platform-service", platform_sign, clock=lambda: NOW)
enroll_issuer = EnrollmentIssuer("enrollment-service", enroll_sign, clock=lambda: NOW)
release_verifier = SecretReleaseVerifier(
    {"quote-service": quote_verify},
    {"platform-service": platform_verify},
    {"enrollment-service": enroll_verify},
    clock=lambda: NOW,
)
subject = SecretReleaseSubject(
    session_id=S,
    secret_id="secret/db-prod",
    attester="tool",
    attester_key_id="ak-7",
    measurement="m2",
    platform_id="tdx-host-4",
)
quote_claim = quote_issuer.issue(subject)
platform_claim = platform_issuer.issue(subject)
enrollment_claim = enroll_issuer.issue(subject)
release = authorize_secret_release(
    subject,
    quote_claim,
    platform_claim,
    enrollment_claim,
    verifier=release_verifier,
)
ok("release accepted with three signed role claims", release["release"])
ok(
    "serialized role claims accepted",
    authorize_secret_release(
        subject,
        quote_claim.to_dict(),
        platform_claim.to_dict(),
        enrollment_claim.to_dict(),
        verifier=release_verifier,
    )["release"],
)
ok(
    "release requires explicit verifier object",
    not authorize_secret_release(subject, quote_claim, platform_claim, enrollment_claim)["release"],
)
ok("legacy three-boolean release API is fail-closed", not secret_release_ok(True, True, True)["release"])
ok(
    "quote-only is insufficient",
    not authorize_secret_release(
        subject, quote_claim, None, None, verifier=release_verifier
    )["release"],
)

other_subject = replace(subject, secret_id="secret/other")
ok(
    "claims for another exact secret subject rejected",
    not authorize_secret_release(
        other_subject,
        quote_claim,
        platform_claim,
        enrollment_claim,
        verifier=release_verifier,
    )["release"],
)
ok(
    "platform claim cannot substitute for quote role",
    not authorize_secret_release(
        subject,
        platform_claim,
        platform_claim,
        enrollment_claim,
        verifier=release_verifier,
    )["release"],
)
ok(
    "signed fail verdict blocks release",
    not authorize_secret_release(
        subject,
        quote_issuer.issue(subject, verdict="fail"),
        platform_claim,
        enrollment_claim,
        verifier=release_verifier,
    )["release"],
)
ok(
    "claim payload mutation rejected",
    not authorize_secret_release(
        subject,
        replace(quote_claim, expires_at=quote_claim.expires_at + 1),
        platform_claim,
        enrollment_claim,
        verifier=release_verifier,
    )["release"],
)
unknown_quote = QuoteVerificationIssuer("unknown-quote", quote_sign, clock=lambda: NOW).issue(subject)
ok(
    "quote issuer outside role allowlist rejected",
    not authorize_secret_release(
        subject, unknown_quote, platform_claim, enrollment_claim, verifier=release_verifier
    )["release"],
)
expired_release_verifier = SecretReleaseVerifier(
    {"quote-service": quote_verify},
    {"platform-service": platform_verify},
    {"enrollment-service": enroll_verify},
    clock=lambda: NOW + 60,
)
ok(
    "expired control claims rejected",
    not expired_release_verifier.authorize(
        subject, quote_claim, platform_claim, enrollment_claim
    )["release"],
)
future_quote = quote_issuer.issue(subject, now=NOW + 100)
ok(
    "future-dated control claim rejected",
    not release_verifier.authorize(
        subject, future_quote, platform_claim, enrollment_claim
    )["release"],
)
short_release_policy = SecretReleaseVerifier(
    {"quote-service": quote_verify},
    {"platform-service": platform_verify},
    {"enrollment-service": enroll_verify},
    clock=lambda: NOW,
    max_ttl_s=30,
)
ok(
    "control claim exceeding verifier TTL policy rejected",
    not short_release_policy.authorize(
        subject, quote_claim, platform_claim, enrollment_claim
    )["release"],
)
wrong_domain_quote = replace(
    quote_claim,
    sig=quote_sign(PLATFORM_CLAIM_DOMAIN + quote_claim._payload()),
)
ok(
    "cross-role domain signature rejected",
    not release_verifier.authorize(
        subject, wrong_domain_quote, platform_claim, enrollment_claim
    )["release"],
)
replayed_platform_unsigned = replace(platform_claim, claim_id=quote_claim.claim_id, sig="")
replayed_platform = replace(
    replayed_platform_unsigned,
    sig=platform_sign(PLATFORM_CLAIM_DOMAIN + replayed_platform_unsigned._payload()),
)
ok(
    "control claim id replay rejected",
    not release_verifier.authorize(
        subject, quote_claim, replayed_platform, enrollment_claim
    )["release"],
)
mutable_quote_map = {"quote-service": quote_verify}
fixed_release_verifier = SecretReleaseVerifier(
    mutable_quote_map,
    {"platform-service": platform_verify},
    {"enrollment-service": enroll_verify},
    clock=lambda: NOW,
)
mutable_quote_map["quote-service"] = wrong_ar_verify
ok(
    "secret verifier copies role trust maps at construction",
    fixed_release_verifier.authorize(
        subject, quote_claim, platform_claim, enrollment_claim
    )["release"],
)

# Existing batch-2 controls remain covered.
store = BitemporalStore()
store.upsert(BitemporalFact("robert", "city", "Moscow", 0.9, valid_from=1000.0))
store.upsert(BitemporalFact("robert", "city", "Dubai", 0.9, valid_from=2000.0))
current = store.current("robert", "city")
ok("only current fact is open (Dubai)", len(current) == 1 and current[0].object_val == "Dubai")
history = store.history("robert", "city")
ok(
    "old fact preserved as historical (valid_until set)",
    len(history) == 2
    and any(item.object_val == "Moscow" and item.valid_until == 2000.0 for item in history),
)
store.upsert(BitemporalFact("wire_transfer", "limit", "no review under 500k", 0.2))
poisoned = store.current("wire_transfer", "limit", min_trust=0.8, require_governed=True)
ok("ASI06: poisoned low-trust fact NOT retrievable as governed truth", len(poisoned) == 0)

# Governed truth is a signed transition, never a caller-supplied boolean.
try:
    BitemporalFact(
        "wire_transfer",
        "limit",
        "caller says governed",
        1.0,
        is_governed_truth=True,
    )
    forged_bool_rejected = False
except TypeError:
    forged_bool_rejected = True
ok("caller-forged is_governed_truth constructor flag rejected", forged_bool_rejected)

forged_object = BitemporalFact("wire_transfer", "review", "skip", 1.0)
object.__setattr__(forged_object, "_governance_claim_id", "caller-forged")
sanitized = store.upsert(forged_object)
ok(
    "upsert strips caller-forged private governance state",
    not sanitized.is_governed_truth
    and not store.current("wire_transfer", "review", require_governed=True),
)
object.__setattr__(sanitized, "_governance_claim_id", "post-upsert-forgery")
ok(
    "mutating a returned snapshot cannot alter store governance",
    not store.current("wire_transfer", "review", require_governed=True),
)
ok("legacy store without fixed verifier cannot promote", not store.promote(sanitized, {}))
try:
    BitemporalStore(True)
    boolean_verifier_rejected = False
except TypeError:
    boolean_verifier_rejected = True
ok("legacy boolean verifier constructor rejected", boolean_verifier_rejected)

promotion_sign, promotion_verify = crypto(b"test-only-governance-promotion-key")
promotion_issuer = GovernancePromotionIssuer(
    "governance-service", promotion_sign, clock=lambda: NOW
)
mutable_promotion_trust = {"governance-service": promotion_verify}
promotion_verifier = GovernancePromotionVerifier(
    mutable_promotion_trust, clock=lambda: NOW
)
governed_store = BitemporalStore(promotion_verifier)
candidate = governed_store.upsert(
    BitemporalFact(
        "wire_transfer",
        "limit",
        "dual approval required",
        1.0,
        transaction_time=NOW,
        valid_from=NOW,
    )
)
promotion = promotion_issuer.issue(candidate, "promotion-1")
mutable_promotion_trust["governance-service"] = wrong_ar_verify
ok(
    "promotion verifier copies issuer allowlist at construction",
    promotion_verifier.verify(promotion, candidate),
)
ok(
    "tampered promotion claim rejected",
    not governed_store.promote(candidate, {**promotion, "fact_digest": "0" * 64}),
)
ok("valid signed exact-fact promotion accepted", governed_store.promote(candidate, promotion))
governed = governed_store.current(
    "wire_transfer", "limit", min_trust=1.0, require_governed=True
)
ok(
    "signed promotion is visible as governed truth",
    len(governed) == 1 and governed[0].is_governed_truth,
)
ok("promotion id replay rejected", not governed_store.promote(candidate, promotion))
replacement = governed_store.upsert(
    BitemporalFact(
        "wire_transfer",
        "limit",
        "triple approval required",
        1.0,
        transaction_time=NOW + 10,
        valid_from=NOW + 10,
    )
)
governed_history = governed_store.history("wire_transfer", "limit")
ok(
    "superseding preserves governed history but new fact stays ungoverned",
    len(governed_history) == 2
    and any(
        item.fact_id == candidate.fact_id
        and item.valid_until == NOW + 10
        and item.is_governed_truth
        for item in governed_history
    )
    and not replacement.is_governed_truth
    and not governed_store.current(
        "wire_transfer", "limit", require_governed=True
    ),
)

svid_sign,svid_verify=crypto(b"test-only-svid-key")
svid_issuer=SVIDIssuer("spire-test",svid_sign,clock=lambda:NOW)
svid_verifier=SVIDVerifier({"spire-test":svid_verify},clock=lambda:NOW)
svid=mint_svid("agent_registry",ttl_sec=100,issuer=svid_issuer,session_id="session-1")
ok("ASI03: expired SVID rejected",not valid_svid(
    svid,now=NOW+200,verifier=svid_verifier,workload="agent_registry",session_id="session-1"))
ok("forged unsigned SVID rejected",not valid_svid(
    {**svid,"sig":"forged"},verifier=svid_verifier,workload="agent_registry",session_id="session-1"))

print(f"\nTALLY DR-fixes-batch2: PASS={P} FAIL={F}")
sys.exit(1 if F else 0)
