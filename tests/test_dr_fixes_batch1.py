import sys, time
import maworld_core.agent_mandate_v2 as mandate_impl
from article12_export import validate_retention, ComplianceViolationError, ART12_FIELDS
from optimistic_verification import (accept_provisional, challenge, finalize,
                                     is_eligible_proposal, is_product_success)
from agent_mandate_v2 import sign_intent, sign_cart, make_payment_mandate, MoneyForgeV2
P=F=0
def ok(n,c,d=""):
    global P,F; b=bool(c); P+=b; F+=(not b); print(("  PASS " if b else "  FAIL ")+n+("" if b else f" <- {d}"))
def _raises(fn,exc):
    try: fn(); return False
    except exc: return True

# Gemini FIX: Article 26(6) retention
ok("90d deployer retention -> ComplianceViolationError (Art 26(6))", _raises(lambda: validate_retention(90,730), ComplianceViolationError))
ok("183/730 retention passes", validate_retention(183,730))
ok("agent-governance field checklist present", "nhi_identity_uri" in ART12_FIELDS and "intent_hash" in ART12_FIELDS)

# GPT FIX #4: irreversible effect must NOT go optimistic (was 'optimistic exposure')
r=accept_provisional("ship_order","irreversible")
ok("irreversible effect BLOCKED from optimistic", r.status=="rejected" and getattr(r,"reason","")=="irreversible_effect_requires_final_verification")
h=accept_provisional("card_hold","holdable")
ok("holdable -> hold proposal (no effect fired)", h.effect_state=="hold_proposed")
challenge(h, True)
ok("fraud signal can only void/reject", h.effect_state=="voided" and h.status=="rejected")
c=accept_provisional("refundable_charge","compensatable")
ok("compensatable remains a proposal", c.effect_state=="compensatable_proposed")
ok("not PRODUCT_SUCCESS while window open", not is_product_success(c))
c2=accept_provisional("refundable_charge","compensatable",challenge_window_s=0); finalize(c2)
ok("elapsed window yields only an eligible proposal, never PRODUCT_SUCCESS",
   is_eligible_proposal(c2) and not is_product_success(c2))

# GPT FIX #5: AP2 mandate replay / cart-substitution / payee-substitution
UK=b"user-key-test-only-32bytes"; MK={"merchant:acme":b"acme-key-test-only-32bytes"}
mf=MoneyForgeV2(UK, MK)
intent=sign_intent(UK,"robert","merchant:acme","subscription.pay",30000,time.time()+3600)
cartA=sign_cart(MK["merchant:acme"],"merchant:acme",{"action":"subscription.pay","sku":"pro","amount_cents":19900},"nonce-1")
pm=make_payment_mandate(UK,intent,cartA,"nonce-1")
ok("valid mandate yields a non-authoritative proposal", mf.evaluate_payment_proposal(intent,cartA,pm)["accepted"])
ok("mandate REPLAY rejected (duplicate payment lineage)", not mf.evaluate_payment_proposal(intent,cartA,pm)["accepted"])
cartB=sign_cart(MK["merchant:acme"],"merchant:acme",{"action":"subscription.pay","sku":"substituted","amount_cents":19900},"nonce-b")
cart_sub=mf.verify(intent,cartB,pm)
ok("cart SUBSTITUTION rejected (exact digest lineage)",
   not cart_sub["accepted"] and "lineage" in cart_sub["reason"])
# payee substitution: different merchant in cart
evil=sign_cart(b"evil-key-test-only-32bytes","merchant:evil",{"action":"subscription.pay","sku":"pro","amount_cents":19900},"n2")
ok("payment builder rejects payee SUBSTITUTION",
   _raises(lambda: make_payment_mandate(UK,intent,evil,"n2"), ValueError))
ok("verifier rejects untrusted substituted payee", "merchant" in mf.verify(intent,evil,pm)["reason"])
# over-cap
big=sign_cart(MK["merchant:acme"],"merchant:acme",{"action":"subscription.pay","sku":"pro","amount_cents":99999},"n3"); pmb=make_payment_mandate(UK,intent,big,"n3")
ok("amount over intent cap rejected", not mf.verify(intent,big,pmb)["accepted"])
tampered=dict(intent); tampered["max_amount_cents"]=999999
ok("tampered user intent signature rejected",not mf.verify(tampered,cartA,pm)["accepted"])
tampered_pm=dict(pm); tampered_pm["amount_cents"]=1
ok("tampered payment mandate signature/amount rejected",not mf.verify(intent,cartA,tampered_pm)["accepted"])
tampered_nonce_cart=dict(cartA); tampered_nonce_cart["merchant_nonce"]="attacker-nonce"
ok("tampered merchant nonce breaks merchant cart signature",
   "cart signature" in mf.verify(intent,tampered_nonce_cart,pm)["reason"])
ok("payment builder rejects nonce not authenticated by cart",
   _raises(lambda: make_payment_mandate(UK,intent,cartA,"attacker-nonce"), ValueError))
forged_pid=dict(pm); forged_pid["payment_identifier"]="f"*64
forged_pid_body={name:forged_pid[name] for name in (
    "user","merchant_did","intent_digest","cart_digest","merchant_nonce","allowed_action","payment_identifier","amount_cents")}
forged_pid["sig"]=mandate_impl._sig(UK,"PAYMENT",forged_pid_body)
forged_result=mf.verify(intent,cartA,forged_pid)
ok("validly re-signed arbitrary payment ID rejected by verifier recomputation",
   not forged_result["accepted"] and "authenticated lineage" in forged_result["reason"])
cartA_nonce2=sign_cart(MK["merchant:acme"],"merchant:acme",{"action":"subscription.pay","sku":"pro","amount_cents":19900},"nonce-2")
pm_nonce2=make_payment_mandate(UK,intent,cartA_nonce2,"nonce-2")
ok("same intent/cart cannot multiply through another merchant-signed nonce",
   mf.verify(intent,cartA_nonce2,pm_nonce2)["accepted"] and
   not mf.evaluate_payment_proposal(intent,cartA_nonce2,pm_nonce2)["accepted"])
wrong_action=sign_cart(MK["merchant:acme"],"merchant:acme",
                       {"action":"refund.issue","sku":"pro","amount_cents":19900},"nonce-action")
ok("cart action outside signed user intent is rejected by builder",
   _raises(lambda: make_payment_mandate(UK,intent,wrong_action,"nonce-action"), ValueError))
ok("cart action outside signed user intent is rejected by verifier",
   "action" in mf.verify(intent,wrong_action,pm)["reason"])
ok("cart requires explicit action", _raises(
   lambda: sign_cart(MK["merchant:acme"],"merchant:acme",{"sku":"pro","amount_cents":1},"nonce-schema"),
   ValueError))
ok("cart rejects floating-point values", _raises(
   lambda: sign_cart(MK["merchant:acme"],"merchant:acme",
                     {"action":"subscription.pay","amount_cents":1,"tax":0.1},"nonce-float"),
   ValueError))
deep={"leaf":"x"}
for _ in range(10): deep={"next":deep}
ok("cart rejects excessive nesting", _raises(
   lambda: sign_cart(MK["merchant:acme"],"merchant:acme",
                     {"action":"subscription.pay","amount_cents":1,"metadata":deep},"nonce-deep"),
   ValueError))
try: mf.charge(intent,cartA,pm); legacy=False
except TypeError: legacy=True
ok("legacy charge API is hard-disabled",legacy)
print(f"\nTALLY DR-fixes-batch1: PASS={P} FAIL={F}"); sys.exit(1 if F else 0)
