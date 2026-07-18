import sys
from improvement_engine import ImprovementProposal, run_improvement, sense, FORBIDDEN
P=F=0
def ok(n,c,d=""):
    global P,F; b=bool(c); P+=b; F+=(not b); print(("  PASS " if b else "  FAIL ")+n+("" if b else f" <- {d}"))
WV={"canon":"continuity_os"}
# SENSE
ok("SENSE fires when metric below threshold", sense(0.6, 0.8) and not sense(0.9, 0.8))
# improvement passes -> CANARY proposal
imp=ImprovementProposal("prompt_x","better few-shot",metric_before=0.70,touches={"prompt"})
ok("improvement -> CANARY proposal", run_improvement(imp, lambda p: 0.82, WV).decision=="PROPOSE_ROLLOUT")
# regression blocked
ok("regression -> BLOCK", run_improvement(imp, lambda p: 0.55, WV).decision=="BLOCK")
# no improvement -> HOLD
ok("no change -> HOLD", run_improvement(imp, lambda p: 0.70, WV).decision=="HOLD")
# forbidden class blocked even if metric improves
bad=ImprovementProposal("gate_logic","loosen gate",metric_before=0.7,touches={"gate"})
ok("forbidden (touches gate) BLOCKED even if better", run_improvement(bad, lambda p: 0.99, WV).decision=="BLOCK")
badks=ImprovementProposal("ks","disable kill switch",metric_before=0.7,touches={"kill_switch"})
ok("forbidden (kill_switch) BLOCKED", run_improvement(badks, lambda p: 0.99, WV).decision=="BLOCK")
# kill-switch fail-closed on evaluation error
def boom(p): raise RuntimeError("eval crashed")
ok("evaluation error -> HOLD (fail-closed)", run_improvement(imp, boom, WV).decision=="HOLD")
# proposal-only
ok("proposal is authoritative=False", imp.authoritative is False)
print(f"\nTALLY improvement-engine: PASS={P} FAIL={F}"); sys.exit(1 if F else 0)
