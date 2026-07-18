import sys, time
from agent_registry import AgentRegistry
from key_custody import Custody, KeyHolder, DOMAINS
P=F=0
def ok(n,c,d=""):
    global P,F; b=bool(c); P+=b; F+=(not b); print(("  PASS " if b else "  FAIL ")+n+("" if b else f" <- {d}"))
# discover
reg=AgentRegistry(); a=reg.register("orchestrator", ttl_sec=100)
ok("registered NHI is known", reg.is_known(a.agent_id))
ok("NHI has SPIFFE id", a.spiffe_id.startswith("spiffe://maworld/orchestrator/"))
ok("unregistered agent = shadow", reg.discover_shadow([a.agent_id,"agent-ROGUE"])==["agent-ROGUE"])
ok("action from shadow blocked (discover-stage)", not reg.admit_action("agent-ROGUE")["admit"])
ok("action from known admitted", reg.admit_action(a.agent_id)["admit"])
exp=reg.register("x", ttl_sec=-1)   # already expired
ok("expired NHI blocked", not reg.admit_action(exp.agent_id)["admit"])
# key custody separation
keys={d:(d+"-key").encode() for d in DOMAINS}
cust=Custody(keys)
ok("gate holder signs for gate", isinstance(cust.holder("gate").sign("gate", b"m"), str))
# the promoter (gate holder) CANNOT sign an approval (approver domain)
try: cust.holder("gate").sign("approver", b"self-approve"); ok("gate holder cannot self-approve",False)
except PermissionError: ok("gate holder cannot sign approver domain (no self-approval)", True)
# approver holder cannot sign gate/human either
try: cust.holder("approver").sign("human_confirm", b"x"); ok("approver cannot forge human",False)
except PermissionError: ok("approver holder cannot sign other domains", True)
# verify is public (verifier can check any domain given the public keys)
v=cust.verifier(keys); sig=cust.holder("approver").sign("approver", b"promote:hash123")
ok("public verify of a real approval", v("approver", b"promote:hash123", sig))
ok("verify rejects forged sig", not v("approver", b"promote:hash123", "deadbeef"))
print(f"\nTALLY registry+custody: PASS={P} FAIL={F}"); sys.exit(1 if F else 0)
