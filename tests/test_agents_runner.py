import sys
from agents_runner import Orchestrator, Challenger, Proposal, Agent
P=F=0
def ok(n,c,d=""):
    global P,F; b=bool(c); P+=b; F+=(not b); print(("  PASS " if b else "  FAIL ")+n+("" if b else f" <- {d}"))

orch=Orchestrator("orchestrator")
out=orch.run_cycle("place a safe testnet order", {"canon":"continuity_os"}, "BINANCE:BTCUSDT", ("BUY","0.001"))
ok("agent cycle STARTS from GLOBAL, cascades down",
   out["cascade"]==["GLOBAL","STRATEGIC","TACTICAL","EXECUTION"])
ok("output is a PROPOSAL, authoritative=False", out["proposal"].authoritative is False)
ok("trace rooted at GLOBAL span (fractal)", out["trace"].root.scope=="GLOBAL")
# CTHA boundary: the agent has NO way to execute an effect
ok("agent has no execute()", not hasattr(orch,"execute"))
ok("agent has no gate/ledger/capability handle",
   not any(hasattr(orch,a) for a in ("gate","ledger","effect_registry","capability","secrets")))
# proposal converts to an ActionSpec for the SEPARATE gate (agent doesn't hold the gate)
spec=out["proposal"].to_action_spec()
ok("proposal -> ActionSpec (hash-addressable) for external gate", len(spec.hash())==64)
# Challenger = dialectic: survives only without verified refutation
ch=Challenger("challenger")
ok("no refutation -> proposal survives (ACT)", ch.critique(out["proposal"])["verdict"]=="ACT")
ok("verified refutation -> HOLD (not executed)",
   ch.critique(out["proposal"], refutations=["units unverified on this venue"])["verdict"]=="HOLD")
# base Agent cannot fire effects either (proposal-only by construction)
ok("base Agent is proposal-only (no effect methods)",
   not any(hasattr(Agent("x"),m) for m in ("execute","submit","place_order","write_canon")))
print(f"\nTALLY agents-runner: PASS={P} FAIL={F}"); sys.exit(1 if F else 0)
