import sys, os, tempfile, time, hmac, hashlib
from sap_bridge import can_promote, promote_entity, delegate, check_delegation, LADDER
from dtaap_z3_bridge import (LiveActionPolicyIR, DefaultDenyPolicyIR,
    prove_no_live_without_confirm, prove_default_deny, solver_backend_available)
from canon_sod import CanonPromoter, Approver, ApprovalVerifier, candidate_hash
P=F=0
def ok(n,c,d=""):
    global P,F; b=bool(c); P+=b; F+=(not b); print(("  PASS " if b else "  FAIL ")+n+("" if b else f" <- {d}"))

# SAP Loop B: promotion only for machine_verified + separate-key approval
ok("truth ladder: only machine_verified eligible", can_promote("machine_verified") and not can_promote("evidenced"))
AK=b"sap-approver-key"
sign=lambda message:hmac.new(AK,message,hashlib.sha256).hexdigest()
verify=lambda message,sig:hmac.compare_digest(sig,sign(message))
POLICY="sap-canon-policy"
approver=Approver("sap-human",sign)
prom=CanonPromoter(os.path.join(tempfile.mkdtemp(),"c.db"),
                   ApprovalVerifier({"sap-human":verify},policy_id=POLICY))
ent={"id":"e1","truth_level":"machine_verified","claim":"donchian edge"}
ok("machine_verified + valid approval -> promoted", promote_entity(
    ent,approver.approve(candidate_hash(ent),"n1",policy_id=POLICY),prom)["ok"])
low={"id":"e2","truth_level":"evidenced","claim":"x"}
ok("evidenced NOT promoted (not machine_verified)",not promote_entity(
    low,approver.approve(candidate_hash(low),"n2",policy_id=POLICY),prom)["promoted"])
# delegation = signed capability, not reputation
CK=b"sap-cap"; tok=delegate(CK,"agentX","reconcile","drive",time.time()+300)
ok("valid signed delegation verifies", check_delegation(CK,tok,"agentX","reconcile","drive"))
ok("bare string delegation rejected", not check_delegation(CK,"trusted-a-lot","agentX","reconcile","drive"))

# DTaaP Z3: restricted Boolean IR checks (not a proof of Python PolicyEngine)
ok("real Z3 backend is installed", solver_backend_available())
ok("Z3 proves safe restricted live-action IR", prove_no_live_without_confirm(LiveActionPolicyIR())==("PROVEN",None))
res,cx=prove_no_live_without_confirm(LiveActionPolicyIR(allow_live_without_confirmation=True))
ok("Z3 finds concrete unsafe-IR counterexample", res=="VIOLATED" and cx=={"allowed":True,"is_live":True,"has_confirm":False}, str(cx))
ok("Z3 proves restricted default-deny IR", prove_default_deny(DefaultDenyPolicyIR())==("PROVEN",None))
res,cx=prove_default_deny(DefaultDenyPolicyIR(default_allow=True))
ok("Z3 refutes default-allow IR", res=="VIOLATED" and cx["allowed"] and not cx["permit"], str(cx))
print(f"\nTALLY sap+dtaap-z3: PASS={P} FAIL={F}"); sys.exit(1 if F else 0)
