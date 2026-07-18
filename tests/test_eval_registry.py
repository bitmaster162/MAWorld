import os, sys
from dataclasses import replace

HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE)
sys.path.insert(0,os.path.join(ROOT,"libs"))
from maworld_core.eval_registry import EvalRegistry, GoldenSet

P=F=0
def ok(name,condition,detail=""):
    global P,F; passed=bool(condition); P+=passed; F+=not passed
    print(("  PASS " if passed else "  FAIL ")+name+("" if passed else f" <- {detail}"))

gs=GoldenSet("gs1",(
    {"input":1,"expected":2},{"input":2,"expected":4},{"input":3,"expected":6},
))
reg=EvalRegistry({"gs1":gs},{"good":lambda x:x*2,"bad":lambda x:x*2 if x<3 else 99})
first=reg.run("prompt","challenger","v1","model-a","gs1","good")
ok("first evaluation is perfect",first.pass_rate==1.0 and first.authoritative is False)
ok("first-ever result cannot promote without baseline",reg.gate(first)=="HOLD_NO_BASELINE")
ok("perfect internal record can pin baseline once",reg.set_baseline("challenger",first))
ok("baseline cannot be overwritten",not reg.set_baseline("challenger",first))
bad=reg.run("prompt","challenger","v2","model-a","gs1","bad")
ok("regression blocks",bad.regression and reg.gate(bad)=="BLOCK_REGRESSION")
good=reg.run("prompt","challenger","v3","model-a","gs1","good")
ok("perfect result is only proposal-eligible",reg.gate(good)=="ELIGIBLE_PROPOSAL")
tampered=replace(bad,regression=False,pass_rate=1.0,passed_cases=3)
ok("mutated record is rejected",reg.gate(tampered)=="BLOCK_UNTRUSTED_RECORD")
forged=replace(good,eval_id="eval-forged")
ok("caller-created record is rejected",reg.gate(forged)=="BLOCK_UNTRUSTED_RECORD")
try:
    reg.run("prompt","challenger","v4","model-a","gs1","good",regression_budget=float("nan"))
    nan_blocked=False
except ValueError: nan_blocked=True
ok("NaN regression budget rejected",nan_blocked)
try:
    EvalRegistry({"empty":GoldenSet("empty",[])},{"good":lambda x:x})
    empty_blocked=False
except ValueError: empty_blocked=True
ok("empty golden set rejected",empty_blocked)

print(f"\nTALLY eval-registry: PASS={P} FAIL={F}"); sys.exit(1 if F else 0)
