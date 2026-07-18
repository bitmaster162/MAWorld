import sys
from reflex_bridge import objective_to_proposal
P=F=0
def ok(n,c,d=""):
    global P,F; b=bool(c); P+=b; F+=(not b); print(("  PASS " if b else "  FAIL ")+n+("" if b else f" <- {d}"))
WV={"canon":"continuity_os"}
# normal objective (improves a metric) -> CANARY proposal, NOT executed
obj={"op":"patch","target":"regime_gate","anomaly":"429 storm on gate","touches":["prompt"],"metric_before":0.7}
r=objective_to_proposal(obj, lambda p: 0.82, WV)
ok("reflex objective -> gated improvement proposal", r["verdict"]=="PROPOSE_ROLLOUT" and not r["executed"])
ok("op routed to gated ActionSpec (not auto-exec)", r["gated_op"] and not r["gated_op"]["authoritative"] and "action_authority" in r["gated_op"]["requires"])
# objective touching the gate/kill-switch -> ALWAYS blocked
bad={"op":"patch","target":"gate","anomaly":"loosen gate","touches":["gate"],"metric_before":0.7}
ok("objective touching gate BLOCKED even if better", objective_to_proposal(bad, lambda p: 0.99, WV)["verdict"]=="BLOCK")
ks={"op":"patch","target":"ks","anomaly":"disable kill switch","touches":["kill_switch"],"metric_before":0.7}
ok("objective disabling kill-switch BLOCKED", objective_to_proposal(ks, lambda p: 0.99, WV)["verdict"]=="BLOCK")
# regression blocked
ok("regressing objective BLOCKED", objective_to_proposal(obj, lambda p: 0.5, WV)["verdict"]=="BLOCK")
# evaluation crash -> kill-switch fail-closed (HOLD)
def boom(p): raise RuntimeError("eval crashed")
ok("evaluation error -> HOLD (fail-closed)", objective_to_proposal(obj, boom, WV)["verdict"]=="HOLD")
# the bridge NEVER executes (reflex exec() stays disabled; MAWorld enforces structurally)
ok("bridge never executes (proposal-only invariant)", objective_to_proposal(obj, lambda p:0.9, WV)["executed"] is False)
print(f"\nTALLY reflex-bridge: PASS={P} FAIL={F}"); sys.exit(1 if F else 0)
