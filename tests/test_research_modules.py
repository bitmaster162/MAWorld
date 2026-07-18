import hashlib, hmac, json, sys, time
from article12_export import Article12Record, ComplianceLog, retention_days, classify_purpose, LOG_PURPOSES
from capability import mint_capability, verify_capability
from remote_attestation import (
    ATTESTED_RELEASE_ACTION,
    AttestedReleaseGate,
    QuoteIssuer,
    QuoteVerifier,
    attested_release,
    make_quote,
    verify_quote,
)
from agent_mandate import sign_intent, verify_intent, authorize_cart
P=F=0
def ok(n,c,d=""):
    global P,F; b=bool(c); P+=b; F+=(not b); print(("  PASS " if b else "  FAIL ")+n+("" if b else f" <- {d}"))

# EU AI Act Art.12 enhancements
ok("retention 6mo general / 24mo biometric", retention_days(False)==183 and retention_days(True)==730)
r=Article12Record("a","venue.order",time.time(),"DENY","cap","high")
ok("high-risk DENY -> risk_situation purpose", classify_purpose(r)=="risk_situation")
ok("3 Art.12(2) logging purposes present", set(LOG_PURPOSES)=={"risk_situation","post_market","operation"})

# Remote attestation (TEE) — defense-in-depth incl TEE.Fail
NOW=int(time.time()); EXPECT="sha256:coderev1"; nonce="chal-1"
QUOTE_KEY=b"tee-vendor-test-key"; ATTACKER_KEY=b"attacker-tee-key"; CAP_KEY=b"release-capability-key"
def signer(key): return lambda message: hmac.new(key,message,hashlib.sha256).hexdigest()
def signature_verifier(key):
    return lambda message, signature: hmac.compare_digest(signer(key)(message), signature)

issuer=QuoteIssuer("tee-main", signer(QUOTE_KEY), clock=lambda:NOW)
trust={"tee-main": signature_verifier(QUOTE_KEY)}
verifier=QuoteVerifier(trust, clock=lambda:NOW, max_ttl_s=60, max_future_skew_s=5)
q=issuer.issue(EXPECT, nonce, ttl_s=60)
ok("valid trusted quote verifies", verifier.verify(q, EXPECT, nonce))
ok("issuer is sign-only", not hasattr(issuer,"verify"))
ok("verifier owns no quote issue method", not hasattr(verifier,"issue"))
ok("wrong code measurement rejected", not verifier.verify(q, "sha256:EVIL", nonce))
ok("wrong/replayed challenge rejected", not verifier.verify(q, EXPECT, "other-nonce"))

tampered=dict(q); tampered["expires_at"]+=1
ok("full payload is signature-bound", not verifier.verify(tampered, EXPECT, nonce))
extra={**q,"unsigned_hint":"trust me"}
ok("unknown unsigned quote fields rejected", not verifier.verify(extra, EXPECT, nonce))
forged=dict(q); forged["sig"]="forged"
ok("forged quote signature rejected", not verifier.verify(forged, EXPECT, nonce))

unsigned={k:v for k,v in q.items() if k!="sig"}
wrong_domain=dict(q); wrong_domain["sig"]=signer(QUOTE_KEY)(
    b"WRONG/ATTESTATION/DOMAIN\x00"+json.dumps(
        unsigned,sort_keys=True,separators=(",",":"),ensure_ascii=False
    ).encode()
)
ok("wrong signature domain rejected", not verifier.verify(wrong_domain, EXPECT, nonce))

expired=QuoteIssuer("tee-main", signer(QUOTE_KEY), clock=lambda:NOW-61).issue(EXPECT,nonce,ttl_s=60)
ok("expired quote rejected", not verifier.verify(expired, EXPECT, nonce))
future=QuoteIssuer("tee-main", signer(QUOTE_KEY), clock=lambda:NOW+6).issue(EXPECT,nonce,ttl_s=30)
ok("quote beyond future-skew policy rejected", not verifier.verify(future, EXPECT, nonce))
overlong=issuer.issue(EXPECT,nonce,ttl_s=61)
ok("signed TTL above verifier policy rejected", not verifier.verify(overlong, EXPECT, nonce))

# The verifier copied its trust map; a later caller mutation cannot add an issuer.
attacker=QuoteIssuer("attacker", signer(ATTACKER_KEY), clock=lambda:NOW)
trust["attacker"]=signature_verifier(ATTACKER_KEY)
ok("issuer allowlist fixed at verifier construction", not verifier.verify(attacker.issue(EXPECT,nonce),EXPECT,nonce))

def cap_validator(token, subject, action, resource):
    return verify_capability(CAP_KEY,token,subject,action,resource,now=NOW)
cap=mint_capability(CAP_KEY,EXPECT,ATTESTED_RELEASE_ACTION,"secret.main",NOW+120)
wrong_resource_cap=mint_capability(CAP_KEY,EXPECT,ATTESTED_RELEASE_ACTION,"secret.other",NOW+120)
calls={"n":0}
def release_secret(): calls["n"]+=1; return "SECRET"
handlers={"secret.main":release_secret}
gate=AttestedReleaseGate(verifier,cap_validator,handlers)
handlers["secret.main"]=lambda:"ATTACKER-VALUE"
released=gate.release(q,EXPECT,nonce,cap,"secret.main")
ok("trusted quote plus signed capability releases fixed handler", released=={"released":True,"value":"SECRET"})
ok("release handler map copied at construction", calls["n"]==1)

before=calls["n"]
ok("bare-string capability denied", not gate.release(q,EXPECT,nonce,"yes","secret.main")["released"])
ok("wrong-resource signed capability denied", not gate.release(q,EXPECT,nonce,wrong_resource_cap,"secret.main")["released"])
ok("boolean capability is not authority", not gate.release(q,EXPECT,nonce,True,"secret.main")["released"])
ok("invalid attestation blocks valid capability", not gate.release(forged,EXPECT,nonce,cap,"secret.main")["released"])
ok("denied paths never invoke release handler", calls["n"]==before)
ok("unregistered per-call release target denied", not gate.release(q,EXPECT,nonce,cap,"secret.other")["released"])

def broken_validator(*_): raise RuntimeError("validator offline")
broken_cap_gate=AttestedReleaseGate(verifier,broken_validator,{"secret.main":release_secret})
ok("capability-validator failure is fail-closed", not broken_cap_gate.release(q,EXPECT,nonce,cap,"secret.main")["released"])
def broken_handler(): raise RuntimeError("secret backend offline")
broken_handler_gate=AttestedReleaseGate(verifier,cap_validator,{"secret.main":broken_handler})
ok("release-handler failure is fail-closed", not broken_handler_gate.release(q,EXPECT,nonce,cap,"secret.main")["released"])

# Compatibility functions have no implicit secrets or per-call authority.
ok("legacy make_quote without issuer fails closed", make_quote(EXPECT,nonce)=={})
ok("legacy verify_quote without verifier fails closed", not verify_quote(q,EXPECT,nonce))
legacy=attested_release(q,EXPECT,nonce,True,lambda:"CALLER-SECRET")
ok("legacy bool plus caller callback fails closed", not legacy["released"])
q2=make_quote(EXPECT,nonce,issuer=issuer)
ok("explicit issuer compatibility wrapper works", verifier.verify(q2,EXPECT,nonce))
ok("explicit verifier compatibility wrapper works", verify_quote(q2,EXPECT,nonce,verifier=verifier))
ok("explicit fixed gate compatibility wrapper works", attested_release(
    q2,EXPECT,nonce,cap,"secret.main",gate=gate
)["released"])
ok("legacy caller-supplied quote timestamp rejected", make_quote(EXPECT,nonce,ts=NOW,issuer=issuer)=={})

# AP2 agent mandate
UK=b"user-key"
intent=sign_intent(UK,"robert","subscription.pay",30000,time.time()+3600)  # up to $300
ok("valid intent mandate verifies", verify_intent(UK,intent))
ok("cart within intent authorized (proposal-only)", authorize_cart(UK,intent,"subscription.pay",19900)["authorized"] and not authorize_cart(UK,intent,"subscription.pay",19900)["authoritative"])
ok("cart over cap rejected", not authorize_cart(UK,intent,"subscription.pay",50000)["authorized"])
ok("cart wrong action rejected", not authorize_cart(UK,intent,"venue.order",100)["authorized"])
forged=dict(intent); forged["max_amount_cents"]=999999
ok("tampered intent (raised cap) rejected", not authorize_cart(UK,forged,"subscription.pay",500000)["authorized"])
exp_intent=sign_intent(UK,"r","x",100,time.time()-1)
ok("expired intent rejected", not verify_intent(UK,exp_intent))
print(f"\nTALLY research-modules: PASS={P} FAIL={F}"); sys.exit(1 if F else 0)
