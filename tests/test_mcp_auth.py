import inspect

import mcp_token_validator as V


NOW = 1_700_000_000
KEY = b"trusted-auth-key-material-32bytes!"
EVIL_KEY = b"attacker-key-material-is-32-bytes!"
ME = "https://mcp.maworld/svc"
ISSUER = "https://auth.maworld"
ORIGIN = "https://app.maworld"

issuer_keys = {ISSUER: KEY}
required_scopes = {"tools.exec"}
origins = {ORIGIN}
issuer = V.MCPTokenIssuer(ISSUER, KEY, clock=lambda: NOW)
verifier = V.MCPTokenVerifier(
    issuer_keys,
    this_server_uri=ME,
    required_scopes=required_scopes,
    origin_allowlist=origins,
    clock=lambda: NOW,
)

P = F = 0


def ok(name, condition, detail=""):
    global P, F
    passed = bool(condition)
    P += passed
    F += not passed
    print(("  PASS " if passed else "  FAIL ") + name + ("" if passed else f" <- {detail}"))


def denied(name, call):
    try:
        call()
        ok(name, False, "unexpectedly accepted")
    except V.MCPAuthError as exc:
        ok(name, exc.http == 401)


good = issuer.issue(audience=ME, scope="tools.exec read", ttl_s=300)
ok("fixed verifier accepts valid audience-bound token", verifier.validate(good, origin=ORIGIN)["ok"])

# Mutating constructor inputs after construction cannot rewrite server trust.
issuer_keys.clear()
issuer_keys["https://evil"] = EVIL_KEY
required_scopes.clear()
origins.clear()
origins.add("https://evil.example")
ok("verifier defensively copied all trust inputs", verifier.validate(good, origin=ORIGIN)["ok"])
try:
    verifier._origin_allowlist = frozenset({"https://evil.example"})
    ok("verifier policy cannot be reassigned after construction", False)
except AttributeError:
    ok("verifier policy cannot be reassigned after construction", True)

wrong_audience = issuer.issue(audience="https://other.server", scope="tools.exec")
denied("wrong audience rejected (RFC 8707)", lambda: verifier.validate(wrong_audience, origin=ORIGIN))

evil_same_key = V.MCPTokenIssuer("https://evil", KEY, clock=lambda: NOW)
untrusted_issuer = evil_same_key.issue(audience=ME, scope="tools.exec")
denied("untrusted issuer rejected", lambda: verifier.validate(untrusted_issuer, origin=ORIGIN))

expired_issuer = V.MCPTokenIssuer(ISSUER, KEY, clock=lambda: NOW - 400)
expired = expired_issuer.issue(audience=ME, scope="tools.exec", ttl_s=60)
denied("expired token rejected", lambda: verifier.validate(expired, origin=ORIGIN))

future_issuer = V.MCPTokenIssuer(ISSUER, KEY, clock=lambda: NOW + 60)
future = future_issuer.issue(audience=ME, scope="tools.exec", ttl_s=60)
denied("future-issued token rejected", lambda: verifier.validate(future, origin=ORIGIN))

no_scope = issuer.issue(audience=ME, scope="read")
denied("insufficient scope rejected", lambda: verifier.validate(no_scope, origin=ORIGIN))
denied("origin outside fixed allowlist rejected", lambda: verifier.validate(good, origin="https://evil.example"))
denied("malformed origin fails closed", lambda: verifier.validate(good, origin=[]))
denied("forged signature rejected", lambda: verifier.validate(good[:-3] + "000", origin=ORIGIN))

try:
    V.MCPTokenVerifier(
        {ISSUER: KEY},
        this_server_uri=ME,
        required_scopes={"tools.exec"},
        origin_allowlist=set(),
        clock=lambda: NOW,
    )
    ok("empty origin policy fails closed", False)
except ValueError:
    ok("empty origin policy fails closed", True)

short_lifetime_verifier = V.MCPTokenVerifier(
    {ISSUER: KEY},
    this_server_uri=ME,
    required_scopes={"tools.exec"},
    origin_allowlist={ORIGIN},
    clock=lambda: NOW,
    max_ttl_s=60,
)
denied("token lifetime cannot exceed fixed verifier policy", lambda: short_lifetime_verifier.validate(good, origin=ORIGIN))

validate_parameters = inspect.signature(V.MCPTokenVerifier.validate).parameters
ok(
    "validation call exposes no key/issuer/audience/scope/origin policy parameters",
    not ({"secret", "issuer_keys", "trusted_issuers", "this_server_uri", "required_scopes", "origin_allowlist", "now"} & set(validate_parameters)),
)

# Exact exploit regression: the attacker aligns its own key, issuer, audience,
# origin and clock in the removed API.  The legacy entry point is a tombstone.
evil_issuer = V.MCPTokenIssuer("https://evil", EVIL_KEY, clock=lambda: NOW)
evil_token = evil_issuer.issue(audience="https://evil-mcp", scope="tools.exec")
denied(
    "attacker-selected key/issuer/origin cannot validate through legacy API",
    lambda: V.validate(
        evil_token,
        secret=EVIL_KEY,
        this_server_uri="https://evil-mcp",
        trusted_issuers={"https://evil"},
        required_scope="tools.exec",
        origin="https://evil.example",
        origin_allowlist={"https://evil.example"},
        now=NOW,
    ),
)
denied(
    "attacker-signed token cannot enter fixed verifier even with allowed origin",
    lambda: verifier.validate(evil_token, origin=ORIGIN),
)

try:
    V.mint(EVIL_KEY, aud=ME, iss=ISSUER, scope="tools.exec", exp=NOW + 60)
    ok("legacy per-call signing API disabled", False)
except RuntimeError:
    ok("legacy per-call signing API disabled", True)

print(f"\nTALLY mcp-auth: PASS={P} FAIL={F}")
raise SystemExit(1 if F else 0)
