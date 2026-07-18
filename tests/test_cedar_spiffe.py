import hashlib,hmac,sys, time
from cedar_align import authorize, authorize_detailed, cedar_backend_available
from spiffe_identity import SVIDIssuer,SVIDVerifier,mint_svid,valid_svid
from policy_engine import Policy, PolicyEngine
P=F=0
def ok(n,c,d=""):
    global P,F; b=bool(c); P+=b; F+=(not b); print(("  PASS " if b else "  FAIL ")+n+("" if b else f" <- {d}"))

# REAL Cedar semantics
ok("real Cedar backend is installed", cedar_backend_available())
pol = 'permit(principal, action == Action::"read", resource);\nforbid(principal, action == Action::"order", resource);'
ok("Cedar: permit read -> Allow", authorize('User::"a"','Action::"read"','Resource::"x"', pol))
ok("Cedar: default-deny unlisted action", not authorize('User::"a"','Action::"write"','Resource::"x"', pol))
ok("Cedar: FORBID overrides (order denied)", not authorize('User::"a"','Action::"order"','Resource::"x"', pol))
bad=authorize_detailed('User::"a"','Action::"read"','Resource::"x"','not valid cedar')
ok("Cedar parse/evaluation errors fail closed", not bad.allowed and "error" in bad.reason)

# our policy_engine mirrors the SAME semantics
pe=PolicyEngine([Policy("PERMIT","*","read","*"), Policy("FORBID","*","order","*")])
ok("mirror: permit read == Cedar Allow", pe.evaluate("a","read","x").allow==authorize('User::"a"','Action::"read"','Resource::"x"',pol))
ok("mirror: default-deny == Cedar", pe.evaluate("a","write","x").allow==authorize('User::"a"','Action::"write"','Resource::"x"',pol))
ok("mirror: forbid-overrides == Cedar", pe.evaluate("a","order","x").allow==authorize('User::"a"','Action::"order"','Resource::"x"',pol))

def sign(m): return hmac.new(b"spiffe-test",m,hashlib.sha256).hexdigest()
def verify(m,s): return hmac.compare_digest(sign(m),s)
issuer=SVIDIssuer("spire-test",sign)
verifier=SVIDVerifier({"spire-test":verify})
# SPIFFE SVID model
s=mint_svid("orchestrator", ttl_sec=100,issuer=issuer,session_id="session-1")
ok("SVID spiffe:// format", s["spiffe_id"].startswith("spiffe://maworld/orchestrator/"))
ok("signed SVID valid within TTL", valid_svid(s,verifier=verifier,workload="orchestrator",session_id="session-1"))
ok("SVID expired after TTL", not valid_svid(s, now=time.time()+200,verifier=verifier,workload="orchestrator",session_id="session-1"))
ok("unsigned implicit SVID validation fails closed",not valid_svid(s))
ok("no long-lived secret (id only, expires)", "expires_at" in s and "secret" not in s)
print(f"\nTALLY cedar+spiffe: PASS={P} FAIL={F}"); sys.exit(1 if F else 0)
