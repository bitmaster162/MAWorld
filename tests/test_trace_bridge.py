import sys
from trace_bridge import Trace, LangfuseExporter
from global_cycle import CycleInvariantError
P=F=0
def ok(n,c,d=""):
    global P,F; b=bool(c); P+=b; F+=(not b); print(("  PASS " if b else "  FAIL ")+n+("" if b else f" <- {d}"))

WV={"canon":"continuity_os"}
tr=Trace("ship freeze-ready", WV)
ok("trace rooted at GLOBAL span", tr.root.scope=="GLOBAL" and tr.root.parent_span_id is None)
strat=tr.child(tr.root,"close blockers")
tac=tr.child(strat,"harden registry")
ex=tr.child(tac,"run suite")
ok("spans descend GLOBAL->STRATEGIC->TACTICAL->EXECUTION", [s.scope for s in (tr.root,strat,tac,ex)]==["GLOBAL","STRATEGIC","TACTICAL","EXECUTION"])
ok("every span carries global objective (fractal)", all(s.node.global_objective_id==tr.root.node.global_objective_id for s in tr.spans))
# cost + gen_ai attrs
tr.record_cost(strat, 0.02, model="claude-opus-4-8", tokens=1500)
tr.record_cost(ex, 0.05, model="claude-sonnet-5", tokens=4000)
ok("OTel gen_ai.* attributes present", tr.spans[1].attributes.get("gen_ai.request.model")=="claude-opus-4-8")
ok("total cost accumulates", tr.total_cost()==0.07)
# bind claim -> cost per verified outcome
tr.bind_claim(ex, "clm-777")
ok("trace_id<->claim_id bound", ex.claim_id=="clm-777")
ok("cost-per-verified-outcome (1 accepted) = total/1", tr.cost_per_verified_outcome({"clm-777"})==0.07)
ok("no verified outcome -> undefined (honest None)", tr.cost_per_verified_outcome({"other"}) is None)
# exporter emits OpenInference spans
exp=LangfuseExporter(); n=exp.export(tr)
ok("Langfuse exporter emits all spans", n==len(tr.spans) and exp.exported[0]["trace_id"]==tr.trace_id)
print(f"\nTALLY trace-bridge: PASS={P} FAIL={F}"); sys.exit(1 if F else 0)
