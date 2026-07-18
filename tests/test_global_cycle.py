import sys
from global_cycle import open_global, derive, validate_chain, CycleInvariantError, CycleNode, SCOPES
P=F=0
def ok(n,c,d=""):
    global P,F; b=bool(c); P+=b; F+=(not b); print(("  PASS " if b else "  FAIL ")+n+("" if b else f" <- {d}"))
def _fail(fn):
    try: fn(); return False
    except CycleInvariantError: return True

WV={"canon":"continuity_os","principle":"fractal+top-down"}
g=open_global("ship MAWorld freeze-ready", WV)
ok("cycle roots at GLOBAL", g.scope=="GLOBAL" and g.parent_id is None)
s=derive(g,"close blockers"); t=derive(s,"harden effect registry"); e=derive(t,"run adversarial suite")
ok("descend GLOBAL->STRATEGIC->TACTICAL->EXECUTION", [n.scope for n in (g,s,t,e)]==SCOPES)
ok("every node reflects the whole (same worldview+objective)",
   all(n.worldview==g.worldview and n.global_objective_id==g.global_objective_id for n in (s,t,e)))
ok("valid chain accepted", validate_chain([g,s,t,e]))
# cannot descend below EXECUTION
ok("EXECUTION is terminal", _fail(lambda: derive(e,"deeper")))
# a cycle NOT starting at GLOBAL is rejected (anomaly-first is banned)
ok("tactical-rooted cycle rejected", _fail(lambda: validate_chain([CycleNode("TACTICAL","x","wv","obj")])))
# level skip rejected (GLOBAL -> TACTICAL)
ok("level skip GLOBAL->TACTICAL rejected", _fail(lambda: validate_chain([g, CycleNode("TACTICAL","x",g.worldview,g.global_objective_id,parent_id=g.node_id)])))
# fractal break: a node with a different worldview is rejected
bad=CycleNode("STRATEGIC","x","OTHER-WV",g.global_objective_id,parent_id=g.node_id)
ok("node losing global reflection rejected", _fail(lambda: validate_chain([g,bad])))
# node not derived from parent rejected
orphan=CycleNode("STRATEGIC","x",g.worldview,g.global_objective_id,parent_id="nope")
ok("orphan (wrong parent) rejected", _fail(lambda: validate_chain([g,orphan])))
print(f"\nTALLY global-cycle: PASS={P} FAIL={F}"); sys.exit(1 if F else 0)
