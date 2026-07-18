"""M6 e2e v2 — rewired onto the hardened modules (closes the confused-deputy + at-most-once +
unit + self-attestation gaps GPT flagged in the original m6_e2e).

  ingress(owner)
    -> action_authority: gate signs a decision bound to the EXACT order ActionSpec hash
    -> risk -> trading_safety.safe_submit (fixed-point -> unit-safe, non-authoritative proposal)
    -> hardened_effect_registry (atomic at-most-once/HOLD, dry_run so nothing live)
    -> evidence_engine v2 (engine-SIGNED acceptance; agent cannot self-attest)
Deny/confused-deputy/replay all blocked BEFORE any effect.
"""
import os, json, hashlib, hmac, secrets, uuid, tempfile
from decimal import Decimal
import action_authority as AA
import hardened_effect_registry as HER
import trading_safety as TS
from action_authority import (ActionSpec, ActionExecutor, ActionVerifier, DecisionIssuer,
                              execute, ConfusedDeputy)
from trading_safety import InstrumentSpec, RiskDecision
from evidence_engine import Claim, ClaimKind as K, EvidenceIssuer, EvidenceAcceptor

BTC = InstrumentSpec("BINANCE:BTCUSDT",3,2,Decimal("0.001"),Decimal("0.01"),Decimal("0.001"),Decimal("100"))
DEMO_ONLY = True


class DryRunTrust:
    """Ephemeral test trust; never import this module as a production boundary."""

    def __init__(self):
        gate_key = secrets.token_bytes(32)
        evidence_key = secrets.token_bytes(32)

        def gate_sign(message):
            return hmac.new(gate_key, message, hashlib.sha256).hexdigest()

        def gate_verify(message, signature):
            return hmac.compare_digest(gate_sign(message), signature)

        def evidence_sign(message):
            return hmac.new(evidence_key, message, hashlib.sha256).hexdigest()

        def evidence_verify(message, signature):
            return hmac.compare_digest(evidence_sign(message), signature)

        self.gate = DecisionIssuer("m6-dryrun-gate", gate_sign)
        self.authority = ActionVerifier({"m6-dryrun-gate": gate_verify})
        self.evidence_sign = evidence_sign
        self.evidence_acceptor = EvidenceAcceptor(
            {"m6-dryrun-evidence": evidence_verify}
        )

class Intent:
    def __init__(self, qf, cid): self.quantity_fixed=qf; self.price_fixed=0; self.client_order_id=cid
class Venue:
    dry_run=True
    def _submit_converted(self,p): return {"venue":"binance","status":"DRY_RUN","payload":p}

def risk(bps):
    """Local risk proposal only; the signed ActionAuthority decision is the actual demo gate."""
    return RiskDecision("ALLOW",bps) if bps<=100 else RiskDecision("DENY",bps,"RISK>1%")

def run(trust, order_qty_fixed, risk_bps, gate_verdict="ALLOW", tamper_spec=False, idem=None, state_dir=None):
    if not isinstance(trust, DryRunTrust):
        raise ValueError("explicit ephemeral DryRunTrust required for this demo")
    st=state_dir or tempfile.mkdtemp(); reg=HER.HardenedEffectRegistry(os.path.join(st,"eff.db"))
    cid=idem or ("ord-"+uuid.uuid4().hex[:8])
    # 1) the ActionSpec is the ACTUAL order (not a shell command)
    spec=ActionSpec("venue.order","BINANCE:BTCUSDT",(cid,str(order_qty_fixed)),
                    handler_id="dryrun.venue.submit")
    # 2) gate signs decision bound to THIS spec hash
    decision=trust.gate.issue(spec, gate_verdict)
    # 3) risk
    rd=risk(risk_bps)
    if rd.kind!="ALLOW":
        fires=reg.fired_count("order-"+cid); reg.close()
        return {"stage":"risk_denied","accepted":False,"fires":fires}
    # 4) execute ONLY if gate authorized THIS exact spec (confused-deputy blocked)
    exec_spec = ActionSpec("venue.order","BINANCE:ETHUSDT",(cid,"9"),
                           handler_id="dryrun.venue.submit") if tamper_spec else spec
    fired={"n":0}
    def do_effect():
        fired["n"]+=1
        return TS.safe_submit(Venue(), Intent(order_qty_fixed,cid), rd, BTC, effect_registry=None)
    effect_payload={"client_order_id":cid,"quantity_fixed":order_qty_fixed,"instrument":"BINANCE:BTCUSDT"}
    def bound_handler(actual_spec):
        return reg.execute_once("order-"+cid, do_effect, tenant="local-dryrun",
                                action=actual_spec.action_type, payload=effect_payload)
    nonce_store=AA.SQLiteNonceStore(os.path.join(st,"authority.db"))
    executor=ActionExecutor({"dryrun.venue.submit":bound_handler},trust.authority,nonce_store)
    try:
        out=execute(exec_spec, decision, executor)
    except ConfusedDeputy as e:
        nonce_store.close()
        reg.close()
        return {"stage":"gate_blocked","accepted":False,"reason":str(e)[:40],"fires":fired["n"]}
    nonce_store.close()
    # 5) evidence: engine-signed acceptance (file sha + effect fired once via registry re-derive)
    art=os.path.join(st,"trade.json"); blob=json.dumps({"cid":cid,"spec":spec.hash()},sort_keys=True).encode()
    open(art,"wb").write(blob); sha=hashlib.sha256(blob).hexdigest()
    cf=Claim(K.FILE_CREATED,{"path":art,"sha256":sha},"orch")
    cw=Claim(K.WORKFLOW_RECOVERED,{"idem_key":"order-"+cid},"orch")
    evidence_issuer=EvidenceIssuer(
        "m6-dryrun-evidence", trust.evidence_sign, registry=reg, file_roots=(st,)
    )
    d1=trust.evidence_acceptor.accept(cf,evidence_issuer.verify(cf))
    d2=trust.evidence_acceptor.accept(cw,evidence_issuer.verify(cw))
    fires=reg.fired_count("order-"+cid); reg.close()
    return {"stage":"done","accepted":d1.accepted and d2.accepted,"fires":fires}

def main():
    R={}
    trust=DryRunTrust()
    with tempfile.TemporaryDirectory() as st:
        a=run(trust,1_000_000,50,idem="M6V2-A",state_dir=st)
        R["happy: accepted, unit-safe, fired once"]= a["stage"]=="done" and a["accepted"] and a["fires"]==1
        b=run(trust,1_000_000,50,idem="M6V2-A",state_dir=st)   # replay against the SAME durable registry
        R["replay: still fired once (idempotent)"]= b["fires"]==1
        c=run(trust,1_000_000,50,gate_verdict="DENY",idem="M6V2-C",state_dir=st)
        R["gate DENY on the ORDER spec -> blocked, 0 fires"]= c["stage"]=="gate_blocked" and c["fires"]==0
        d=run(trust,1_000_000,50,tamper_spec=True,idem="M6V2-D",state_dir=st)
        R["confused-deputy: exec different spec -> blocked, 0 fires"]= d["stage"]=="gate_blocked" and d["fires"]==0
        e=run(trust,1_000_000,250,idem="M6V2-E",state_dir=st)
        R["risk DENY 2.5% -> blocked pre-venue"]= e["stage"]=="risk_denied" and e["fires"]==0
    print("== M6 e2e v2 (rewired on hardened modules) ==")
    ok=True
    for k,v in R.items(): print(("PASS" if v else "FAIL"),"|",k); ok=ok and v
    print("\n"+("M6 v2 OK — hash-bound gate, unit-safe, replay-safe dry-run evidence" if ok else "M6 v2 FAIL"))
    import sys; sys.exit(0 if ok else 1)
if __name__=="__main__": main()
