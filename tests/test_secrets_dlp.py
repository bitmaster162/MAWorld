from __future__ import annotations

import base64
import hashlib
import hmac
import os
import sys
import tempfile
from dataclasses import replace

from maworld_core import dlp_redact as D
from maworld_core.secrets_broker import (
    MAX_JSON_STRING_CHARS,
    CapabilityIssuer,
    CapabilityReplayStore,
    CapabilityVerifier,
    SecretDispatchError,
    SecretScope,
    SecretsBroker,
    TransportOperation,
)


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
clock = {"now": NOW}
sign, verify = crypto(b"test-only-capability-key")
_, wrong_verify = crypto(b"wrong-test-only-capability-key")
issuer = CapabilityIssuer("owner-control", sign, clock=lambda: clock["now"])
verifier = CapabilityVerifier({"owner-control": verify}, clock=lambda: clock["now"])

SECRET = "SECRET_API_VALUE_123"
TRANSPORT_ID = "test.exchange"
OPERATION_ID = "test.exchange.balance.read"
METHOD = "POST"
ENDPOINT_ID = "test.exchange.v1.balance"
transport_state = {"mode": "ok"}
transport_calls = []


def prepare_balance_request(raw):
    if not isinstance(raw, dict) or not {"account"} <= set(raw) <= {"account", "note"}:
        raise ValueError("invalid balance request")
    if raw.get("account") != "primary":
        raise ValueError("invalid account")
    if "note" in raw and not isinstance(raw["note"], str):
        raise ValueError("invalid note")
    return dict(raw)


def nested_response(depth):
    value = "leaf"
    for _ in range(depth):
        value = {"child": value}
    return value


def trusted_transport(secret, request):
    # A trusted broker-side adapter may see the secret. It records only a
    # boolean assertion, never the value.
    transport_calls.append({"secret_ok": secret == SECRET, "request": request})
    mode = transport_state["mode"]
    if mode == "error":
        raise RuntimeError("upstream failed with " + secret)
    if mode == "leak":
        return {"unsafe": secret}
    if mode == "leak_b64":
        return {"unsafe": base64.b64encode(secret.encode()).decode()}
    if mode == "leak_hex":
        return {"unsafe": secret.encode().hex()}
    if mode == "leak_split":
        return {"unsafe": ".".join(secret)}
    if mode == "huge":
        return {"blob": "x" * (MAX_JSON_STRING_CHARS + 1)}
    if mode == "total":
        return {"chunks": ["x" * 300 for _ in range(1_000)]}
    if mode == "nested":
        return nested_response(20)
    return {"ok": True, "request_id": "req-7"}


operation = TransportOperation(
    transport_id=TRANSPORT_ID,
    operation_id=OPERATION_ID,
    method=METHOD,
    endpoint_id=ENDPOINT_ID,
    prepare_request=prepare_balance_request,
    transport=trusted_transport,
)
mutable_operations = {OPERATION_ID: operation}
replay_temp = tempfile.TemporaryDirectory(prefix="maworld-capability-replay-")
replay_path = os.path.join(replay_temp.name, "replay.sqlite3")
replay_store = CapabilityReplayStore(replay_path)
broker = SecretsBroker(verifier, mutable_operations, replay_store, clock=lambda: clock["now"])
mutable_operations.clear()
broker.put("binance_key", "trader", "exchange_cred", SECRET)
scope = SecretScope(
    subject_id="agent-7",
    secret_id="binance_key",
    role="trader",
    data_class="exchange_cred",
    transport_id=TRANSPORT_ID,
    operation_id=OPERATION_ID,
    method=METHOD,
    endpoint_id=ENDPOINT_ID,
)


def body(note=None):
    value = {"account": "primary"}
    if note is not None:
        value["note"] = note
    return value


# Exact signed operation, frozen request and one-use behavior.
token = issuer.issue(scope)
wrong_role = replace(scope, role="attacker")
ok("wrong-role scope rejected", not broker.checkout(wrong_role, token, body())["ok"])
mutable_body = body("original")
checkout = broker.checkout(scope, token, mutable_body)
mutable_body["note"] = "substituted-after-checkout"
ok(
    "checkout returns an opaque reference, never plaintext",
    checkout["ok"] and SECRET not in str(checkout) and "reference" in checkout,
)
ok("capability token is consumed by checkout", not broker.checkout(scope, token, body())["ok"])
try:
    broker.dispatch(checkout["reference"], body("replacement"))
    dispatch_request_injection_rejected = False
except TypeError:
    dispatch_request_injection_rejected = True
ok("dispatch has no request-substitution argument", dispatch_request_injection_rejected)
response = broker.dispatch(checkout["reference"])
sent = transport_calls[-1]["request"]
ok(
    "dispatch uses secret only inside fixed trusted operation",
    response == {"ok": True, "request_id": "req-7"}
    and transport_calls[-1]["secret_ok"]
    and SECRET not in str(response),
)
ok(
    "checkout freezes an alias-free body",
    sent["body"]["note"] == "original" and "substituted" not in str(sent),
)
ok(
    "broker reconstructs exact method and endpoint",
    sent["operation_id"] == OPERATION_ID
    and sent["method"] == METHOD
    and sent["endpoint_id"] == ENDPOINT_ID,
)
try:
    broker.dispatch(checkout["reference"])
    reference_replay_rejected = False
except SecretDispatchError:
    reference_replay_rejected = True
ok("checkout reference is one-use", reference_replay_rejected)
ok("broker copies the fixed operation registry", OPERATION_ID in repr(broker))

# Legacy plaintext/signing helpers cannot be recovered with any key argument.
try:
    broker.grant("binance_key", "trader", "exchange_cred")
    legacy_grant_rejected = False
except PermissionError:
    legacy_grant_rejected = True
ok("legacy broker.grant is fail-closed", legacy_grant_rejected)
try:
    broker.resolve("anything", b"guessed-enclave-key")
    legacy_resolve_rejected = False
except PermissionError:
    legacy_resolve_rejected = True
ok("legacy plaintext resolve is fail-closed", legacy_resolve_rejected)

# Signature, issuer, full operation payload, TTL/future, serialization and trust maps.
ok("forged string capability rejected", not broker.checkout(scope, "deadbeef", body())["ok"])
fresh = issuer.issue(scope)
tampered = replace(fresh, expires_at=fresh.expires_at + 1)
ok("full capability payload mutation rejected", not verifier.verify(tampered, scope).accepted)
tampered_endpoint = replace(scope, endpoint_id="test.exchange.v1.withdraw")
ok("signed capability is bound to endpoint id", not verifier.verify(fresh, tampered_endpoint).accepted)
tampered_method = replace(scope, method="GET")
ok("signed capability is bound to method", not verifier.verify(fresh, tampered_method).accepted)
wrong_key_verifier = CapabilityVerifier({"owner-control": wrong_verify}, clock=lambda: clock["now"])
ok("wrong verifier key rejected", not wrong_key_verifier.verify(fresh, scope).accepted)
other_issuer = CapabilityIssuer("unknown-owner", sign, clock=lambda: clock["now"])
ok("issuer outside fixed allowlist rejected", not verifier.verify(other_issuer.issue(scope), scope).accepted)
future = issuer.issue(scope, now=NOW + 100)
ok("future-dated capability rejected", not verifier.verify(future, scope).accepted)
expired_verifier = CapabilityVerifier({"owner-control": verify}, clock=lambda: NOW + 30)
ok("expired capability rejected", not expired_verifier.verify(fresh, scope).accepted)
short_ttl_policy = CapabilityVerifier({"owner-control": verify}, clock=lambda: NOW, max_ttl_s=10)
ok("capability exceeding verifier TTL policy rejected", not short_ttl_policy.verify(fresh, scope).accepted)
ok("serialized signed capability accepted", verifier.verify(issuer.issue(scope).to_dict(), scope).accepted)
cross_domain = replace(fresh, sig=sign(b"OTHER-DOMAIN\x00" + fresh._payload()))
ok("cross-domain signature rejected", not verifier.verify(cross_domain, scope).accepted)

mutable_trust = {"owner-control": verify}
fixed_verifier = CapabilityVerifier(mutable_trust, clock=lambda: NOW)
mutable_trust["owner-control"] = wrong_verify
ok("verifier copies issuer trust map", fixed_verifier.verify(issuer.issue(scope), scope).accepted)

# Unknown operations and any caller-controlled routing/header fields fail closed.
unknown_scope = replace(
    scope,
    transport_id="attacker.transport",
    operation_id="attacker.operation",
    endpoint_id="attacker.endpoint",
)
unknown_token = issuer.issue(unknown_scope)
ok("capability cannot inject an unregistered operation", not broker.checkout(unknown_scope, unknown_token, body())["ok"])
ok("failed configured checkout consumes valid token", not broker.checkout(unknown_scope, unknown_token, body())["ok"])

before = len(transport_calls)
ssrf_token = issuer.issue(scope)
ssrf = broker.checkout(
    scope,
    ssrf_token,
    {"account": "primary", "url": "http://169.254.169.254/latest/meta-data"},
)
ok("caller URL/SSRF substitution is rejected", not ssrf["ok"] and len(transport_calls) == before)
ok("rejected SSRF request still consumes token", not broker.checkout(scope, ssrf_token, body())["ok"])
header_token = issuer.issue(scope)
header_injection = broker.checkout(
    scope,
    header_token,
    {"account": "primary", "headers": {"Authorization": "attacker"}},
)
ok("caller header substitution is rejected", not header_injection["ok"])
huge_request = broker.checkout(
    scope,
    issuer.issue(scope),
    body("x" * (MAX_JSON_STRING_CHARS + 1)),
)
ok("oversized request string is rejected before transport", not huge_request["ok"])

# Error, response bounds and conservative secret-reflection sanitization.
transport_state["mode"] = "error"
error_checkout = broker.checkout(scope, issuer.issue(scope), body())
try:
    broker.dispatch(error_checkout["reference"])
    sanitized_error = False
except SecretDispatchError as error:
    deepest = error.__traceback__
    while deepest is not None and deepest.tb_next is not None:
        deepest = deepest.tb_next
    broker_locals_clean = bool(
        deepest is not None
        and deepest.tb_frame.f_locals.get("secret") is None
        and deepest.tb_frame.f_locals.get("response") is None
        and deepest.tb_frame.f_locals.get("bounded_response") is None
    )
    sanitized_error = (
        SECRET not in str(error)
        and "upstream" not in str(error)
        and error.__context__ is None
        and error.__cause__ is None
        and broker_locals_clean
    )
ok("transport exception is sanitized", sanitized_error)


def mode_is_blocked(mode):
    transport_state["mode"] = mode
    checkout = broker.checkout(scope, issuer.issue(scope), body())
    try:
        broker.dispatch(checkout["reference"])
        return False
    except SecretDispatchError as error:
        return SECRET not in str(error) and error.__context__ is None


ok("transport cannot reflect plaintext secret", mode_is_blocked("leak"))
ok("transport cannot reflect base64 secret", mode_is_blocked("leak_b64"))
ok("transport cannot reflect hex secret", mode_is_blocked("leak_hex"))
ok("transport cannot reflect separator-obfuscated secret", mode_is_blocked("leak_split"))
ok("oversized transport response is rejected", mode_is_blocked("huge"))
ok("transport response total-byte limit is enforced", mode_is_blocked("total"))
ok("over-deep transport response is rejected", mode_is_blocked("nested"))
transport_state["mode"] = "ok"
ok("broker repr redacts values", SECRET not in repr(broker) and "REDACTED" in repr(broker))

# Existing DLP redaction controls remain separate from broker defense in depth.
payload = {
    "msg": "key is sk_live_abcdef123456 email bob@x.com card 4111 1111 1111 1111",
    "tok": "Bearer abcdef1234567890xyz",
}
redacted = D.redact(payload, known_secrets=[SECRET])
blob = str(redacted)
ok("DLP redacts API key", "sk_live_abcdef123456" not in blob and "REDACTED:API_KEY" in blob)
ok("DLP redacts email", "bob@x.com" not in blob)
ok("DLP redacts PAN", "4111 1111 1111 1111" not in blob)
ok("DLP redacts bearer token", "abcdef1234567890xyz" not in blob)
ok("DLP exact known-secret leak detected", D.leak_detected({"x": "..." + SECRET + "..."}, [SECRET]))
ok("DLP leaves safe text intact", D.redact_text("hello world") == "hello world")

# One-use consumption survives a second broker connection and a store restart.
durable_token = issuer.issue(scope)
first_checkout = broker.checkout(scope, durable_token, body())
replica_store = CapabilityReplayStore(replay_path)
replica = SecretsBroker(verifier, {OPERATION_ID: operation}, replica_store, clock=lambda: clock["now"])
replica.put("binance_key", "trader", "exchange_cred", SECRET)
ok("capability cannot replay on a second broker replica",
   first_checkout["ok"] and not replica.checkout(scope, durable_token, body())["ok"])
replica_store.close(); replay_store.close()
restarted_store = CapabilityReplayStore(replay_path)
restarted = SecretsBroker(verifier, {OPERATION_ID: operation}, restarted_store, clock=lambda: clock["now"])
restarted.put("binance_key", "trader", "exchange_cred", SECRET)
ok("capability consumption survives broker restart",
   not restarted.checkout(scope, durable_token, body())["ok"])
restarted_store.close(); replay_temp.cleanup()

print(f"\nTALLY secrets+DLP: PASS={P} FAIL={F}")
sys.exit(1 if F else 0)
