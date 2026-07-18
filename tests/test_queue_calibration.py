import hashlib, hmac, sys, os, tempfile
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT,"libs"))
from maworld_core.queue_calibration import (QueueExpectation, QueueOutcome, audit, QueueCalibrator,
    calibrate_impact, LATENCY_OVERSHOOT_ALERT_THRESHOLD, MAX_STEP, FLOW_RATE_FLOOR, FLOW_RATE_CEIL)
from maworld_core.action_authority import (ActionVerifier, DecisionIssuer, SQLiteNonceStore,
                                           HumanApprovalIssuer)
P=F=0
def ok(n,c,d=""):
    global P,F; b=bool(c); P+=b; F+=(not b); print(("  PASS " if b else "  FAIL ")+n+("" if b else f" <- {d}"))

# the guide's constants and formulas, kept verbatim
ok("guide constant preserved: threshold = 2.0s", LATENCY_OVERSHOOT_ALERT_THRESHOLD==2.0)
a=audit(QueueExpectation(0.9,1.0), QueueOutcome(0.4,5.0))
ok("Shortfall = max(0, fill_exp - fill_act)", abs(a["shortfall"]-0.5)<1e-9, str(a))
ok("Overshoot = max(0, latency_act - clear_time_exp)", abs(a["overshoot"]-4.0)<1e-9)
ok("overshoot > 2.0s triggers recalibration", a["recalibrate"] and a["action"]=="recalibrate_queue_simulator")
ok("negative errors clamp to zero (no free credit)",
   audit(QueueExpectation(0.4,5.0), QueueOutcome(0.9,1.0))["shortfall"]==0.0)
ok("within threshold -> no recalibration", not audit(QueueExpectation(0.9,1.0), QueueOutcome(0.9,1.2))["recalibrate"])
ok("at exactly the threshold -> no trigger (strictly greater)",
   not audit(QueueExpectation(0.9,1.0), QueueOutcome(0.9,3.0))["recalibrate"])

# our addition: bounded, proposal-only
def signer(key): return lambda message: hmac.new(key,message,hashlib.sha256).hexdigest()
def verifier(key):
    return lambda message,sig: hmac.compare_digest(hmac.new(key,message,hashlib.sha256).hexdigest(),sig)

GATE_KEY=b"queue-gate-test-key"; OWNER_KEY=b"queue-owner-test-key"
gate=DecisionIssuer("queue-gate",signer(GATE_KEY))
owner=HumanApprovalIssuer("queue-owner",signer(OWNER_KEY))
authority=ActionVerifier({"queue-gate":verifier(GATE_KEY)},{"queue-owner":verifier(OWNER_KEY)})
store=SQLiteNonceStore(os.path.join(tempfile.mkdtemp(),"queue-nonces.db"))
c=QueueCalibrator(1.0,calibrator_id="arena-main",verifier=authority,nonce_store=store)
r=c.observe(QueueExpectation(0.9,1.0), QueueOutcome(0.4,5.0))
p=r["proposal"]
ok("recalibration is a PROPOSAL, not a write", p is not None and p["authoritative"] is False)
ok("proposal makes flow_rate MORE conservative (down)", p["to"] < p["from"])
ok("flow_rate unchanged until approved", c.flow_rate==1.0)
ok("bare boolean-style/no-decision apply refused", c.apply(p)["applied"] is False)
decision=gate.issue(c.action_spec(p),"REQUIRE_CONFIRMATION")
ok("signed decision without owner confirmation refused", c.apply(p,decision)["applied"] is False)
ok("signed exact decision + owner confirmation moves the param",
   c.apply(p,decision,owner.confirm(decision))["applied"] and c.flow_rate==p["to"])
ok("decision nonce cannot be replayed", c.apply(p,decision,owner.confirm(decision))["applied"] is False)
ok("step is bounded by MAX_STEP", p["step_pct"] <= MAX_STEP*100 + 1e-9, str(p["step_pct"]))
ok("out-of-bounds proposal refused",
   c.apply({"param":"flow_rate","to":99.0,"from":c.flow_rate,"authoritative":False})["applied"] is False)
ok("oversized step refused even if in bounds",
   c.apply({"param":"flow_rate","to":c.flow_rate*0.1,"from":c.flow_rate,
            "authoritative":False})["applied"] is False)
c2=QueueCalibrator(FLOW_RATE_FLOOR)
p2=c2.observe(QueueExpectation(0.9,1.0), QueueOutcome(0.1,60.0))["proposal"]
ok("calibrator cannot tune itself below the floor", p2["to"] >= FLOW_RATE_FLOOR - 1e-9, str(p2))
ok("no proposal when healthy", c.observe(QueueExpectation(0.9,1.0), QueueOutcome(0.9,1.1))["proposal"] is None)
s=c.stats(); ok("stats track observations + recalibrations", s["observations"]>=2 and s["recalibrations"]>=1, str(s))

# the generalisation that closes OUR gap: eta calibrated from realized vs predicted impact
r=calibrate_impact(predicted_bps=6.3, realized_bps=9.0, eta_coeff=0.5)
ok("under-predicted impact -> raise eta", r["proposal"]["to"] > 0.5 and "under-predicted" in r["proposal"]["direction"])
r=calibrate_impact(predicted_bps=9.0, realized_bps=6.3, eta_coeff=0.5)
ok("over-predicted impact -> lower eta", r["proposal"]["to"] < 0.5 and "over-predicted" in r["proposal"]["direction"])
ok("impact calibration is bounded", abs(calibrate_impact(1.0, 100.0, 0.5)["proposal"]["to"] - 0.5) <= 0.5*MAX_STEP+1e-9)
ok("impact calibration is proposal-only", calibrate_impact(6.3, 9.0, 0.5)["proposal"]["authoritative"] is False)
ok("no prediction -> nothing to calibrate", calibrate_impact(0.0, 9.0, 0.5)["proposal"] is None)

# a valid signature for a different target/proposal cannot be replayed here
c3=QueueCalibrator(1.0,calibrator_id="arena-other",verifier=authority,
                   nonce_store=SQLiteNonceStore(os.path.join(tempfile.mkdtemp(),"queue-nonces.db")))
p3=c3.observe(QueueExpectation(0.9,1.0),QueueOutcome(0.4,5.0))["proposal"]
wrong_target=gate.issue(c.action_spec({**p3,"from":c.flow_rate,"to":c.flow_rate}),"ALLOW")
ok("signed decision for another calibrator/proposal is rejected", not c3.apply(p3,wrong_target)["applied"])

print(f"\nTALLY queue-calibration: PASS={P} FAIL={F}"); sys.exit(1 if F else 0)
