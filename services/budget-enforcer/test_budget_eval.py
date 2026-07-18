import os, tempfile, time
from dataclasses import replace
from budget_router import BudgetRouter, PriceCatalog, RolePolicy, UsageEstimate
from eval_registry import EvalRegistry, GoldenSet

R={}
cat=PriceCatalog({("openai","gpt-safe"):{"input":5,"cached":0.5,"output":30}},
                 source="official",fetched_at=time.time())
orch=RolePolicy("orchestrator","openai/gpt-safe","none/disabled",1.0,0.1,0.1,
                direct_api_required=True)
br=BudgetRouter(cat,{"orchestrator":orch},os.path.join(tempfile.mkdtemp(),"budget.db"))
usage=UsageEstimate(10_000,1_000,2_000)
d=br.route("orchestrator","P2","INTERNAL",usage)
R["route is non-authoritative proposal"] = d.decision=="ELIGIBLE_PROPOSAL" and not d.authoritative
R["fixed direct lane"] = d.lane=="direct"
R["unknown role denied"] = br.route("attacker","P0","PUBLIC",usage).decision=="DENY"
R["NaN/caller cost shape denied"] = br.route("orchestrator","P0","PUBLIC",object()).decision=="DENY"
stale=BudgetRouter(replace(cat,fetched_at=time.time()-100000,freshness_sla_h=1),
                   {"orchestrator":orch},os.path.join(tempfile.mkdtemp(),"stale.db"))
R["stale prices HOLD even P0"] = stale.route("orchestrator","P0","PUBLIC",usage).decision=="HOLD"
R["fallback cannot bypass checks"] = br.fallback(orch).decision=="HOLD"
try: br.observe_cost("orchestrator",-999); observed=False
except RuntimeError: observed=True
R["caller cost mutation disabled"] = observed

gs=GoldenSet("gs1",[{"input":1,"expected":2},{"input":2,"expected":4}])
er=EvalRegistry({"gs1":gs},{"good":lambda x:x*2,"bad":lambda x:0})
base=er.run("prompt","challenger","v1","model","gs1","good")
R["first eval held"] = er.gate(base)=="HOLD_NO_BASELINE"
R["baseline exact and immutable"] = er.set_baseline("challenger",base) and not er.set_baseline("challenger",base)
bad=er.run("prompt","challenger","v2","model","gs1","bad")
R["regression blocks"] = er.gate(bad)=="BLOCK_REGRESSION"
good=er.run("prompt","challenger","v3","model","gs1","good")
R["good eval only proposal eligible"] = er.gate(good)=="ELIGIBLE_PROPOSAL" and not good.authoritative

print("== BudgetRouter + EvalRegistry hardened ==")
ok_all=True
for k,v in R.items(): print(("PASS" if v else "FAIL"),"|",k); ok_all=ok_all and v
print("\n"+("ALL PASS ("+str(sum(R.values()))+"/"+str(len(R))+")" if ok_all else "FAIL"))
import sys; sys.exit(0 if ok_all else 1)
