import hashlib, hmac, os, tempfile, time
from dataclasses import replace
from action_authority import (ActionSpec, ActionExecutor, ActionVerifier, DecisionIssuer,
    HumanApprovalIssuer, SQLiteNonceStore, gate_decide, human_confirm, execute, ConfusedDeputy)

P=F=0
def ok(n,c,d=""):
    global P,F; b=bool(c); P+=b; F+=(not b); print(("  PASS " if b else "  FAIL ")+n+("" if b else f" <- {d}"))

def signer(key): return lambda message: hmac.new(key,message,hashlib.sha256).hexdigest()
def verifier(key):
    def check(message,sig):
        return hmac.compare_digest(hmac.new(key,message,hashlib.sha256).hexdigest(),sig)
    return check

GATE_KEY=b"gate-owned-by-separate-domain"; HUMAN_KEY=b"human-owned-by-control-plane"
gate=DecisionIssuer("gate-main",signer(GATE_KEY))
owner=HumanApprovalIssuer("owner-main",signer(HUMAN_KEY))
trusted=ActionVerifier({"gate-main":verifier(GATE_KEY)},{"owner-main":verifier(HUMAN_KEY)})

def ran(spec, decision, authority=trusted, confirmation=None):
    fired={"n":0}
    def handler(actual_spec): fired["n"]+=1; return "done"
    store=SQLiteNonceStore(os.path.join(tempfile.mkdtemp(),"nonce.db"))
    executor=ActionExecutor({spec.resolved_handler_id():handler},authority,store)
    try:
        execute(spec,decision,executor,confirmation=confirmation); result=(True,fired["n"])
    except ConfusedDeputy: result=(False,fired["n"])
    store.close(); return result

shell=ActionSpec("shell.exec","npm test",("--ci",),handler_id="tests.run")
order=ActionSpec("venue.order","BINANCE:BTCUSDT",("BUY","0.001"),handler_id="venue.submit")

e,n=ran(shell,gate.issue(shell,"ALLOW")); ok("trusted issuer + exact spec executes",e and n==1)
e,n=ran(order,gate.issue(shell,"ALLOW")); ok("shell approval cannot run order",(not e) and n==0)

d=gate.issue(order,"REQUIRE_CONFIRMATION")
e,n=ran(order,d); ok("confirmation required",(not e) and n==0)
e,n=ran(order,d,confirmation=owner.confirm(d)); ok("trusted owner confirms exact decision",e and n==1)
wrong=gate.issue(shell,"REQUIRE_CONFIRMATION")
e,n=ran(order,d,confirmation=owner.confirm(wrong)); ok("approval for another decision rejected",(not e) and n==0)

e,n=ran(shell,gate.issue(shell,"DENY")); ok("DENY refused",(not e) and n==0)
forged=replace(gate.issue(order,"ALLOW"),sig="deadbeef")
e,n=ran(order,forged); ok("forged decision signature refused",(not e) and n==0)
tampered=replace(gate.issue(order,"DENY"),verdict="ALLOW")
e,n=ran(order,tampered); ok("tampered verdict refused",(not e) and n==0)

base=gate.issue(order,"ALLOW")
payload_tamper=ActionSpec("venue.order","BINANCE:BTCUSDT",("BUY","9.999"),handler_id="venue.submit")
e,n=ran(payload_tamper,base); ok("payload params hash-bound",(not e) and n==0)
handler_tamper=ActionSpec("venue.order","BINANCE:BTCUSDT",("BUY","0.001"),handler_id="secrets.export")
e,n=ran(handler_tamper,base); ok("handler id signed",(not e) and n==0)

fired={"n":0}
def evil(): fired["n"]+=1
try: execute(shell,gate.issue(shell,"ALLOW"),evil); callback_blocked=False
except ConfusedDeputy: callback_blocked=True
ok("per-call callback forbidden",callback_blocked and fired["n"]==0)

now=2_000_000_000
fixed=ActionVerifier({"gate-main":verifier(GATE_KEY)},{"owner-main":verifier(HUMAN_KEY)},clock=lambda:now)
expired=gate.issue(shell,"ALLOW",now=now-100,ttl_s=10)
e,n=ran(shell,expired,fixed); ok("expired decision refused",(not e) and n==0)
future=gate.issue(shell,"ALLOW",now=now+100,ttl_s=10)
e,n=ran(shell,future,fixed); ok("future decision refused",(not e) and n==0)

attacker_gate=DecisionIssuer("attacker-gate",signer(b"attacker"))
e,n=ran(shell,attacker_gate.issue(shell,"ALLOW")); ok("caller-chosen issuer is not trusted",(not e) and n==0)
attacker_owner=HumanApprovalIssuer("attacker-owner",signer(b"attacker-human"))
e,n=ran(order,d,confirmation=attacker_owner.confirm(d)); ok("caller-chosen human approver rejected",(not e) and n==0)

legacy=gate_decide(shell,"ALLOW")
e,n=ran(shell,legacy); ok("legacy gate helper is proposal-only and non-executable",(not e) and n==0)
try: human_confirm(d); legacy_human_blocked=False
except ConfusedDeputy: legacy_human_blocked=True
ok("legacy self-confirm helper disabled",legacy_human_blocked)

replay_decision=gate.issue(shell,"ALLOW",now=now)
count={"n":0}; replay_db=os.path.join(tempfile.mkdtemp(),"nonce.db")
def fixed_handler(spec): count["n"]+=1; return "done"
store=SQLiteNonceStore(replay_db)
ActionExecutor({"tests.run":fixed_handler},fixed,store).execute(shell,replay_decision); store.close()
store2=SQLiteNonceStore(replay_db)
try:
    ActionExecutor({"tests.run":fixed_handler},fixed,store2).execute(shell,replay_decision); replay_blocked=False
except ConfusedDeputy: replay_blocked=True
store2.close(); ok("nonce survives executor/store restart",replay_blocked and count["n"]==1)

import sys
print(f"\nTALLY action-authority: PASS={P} FAIL={F}")
sys.exit(1 if F else 0)
