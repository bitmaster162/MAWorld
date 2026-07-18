import os, sys, tempfile, threading
from budget_router import BudgetRouter, BudgetError
P=F=0
def ok(n,c,d=""):
    global P,F; b=bool(c); P+=b; F+=(not b); print(("  PASS " if b else "  FAIL ")+n+("" if b else f" <- {d}"))
def _fail(fn):
    try: fn(); return False
    except BudgetError: return True

db=os.path.join(tempfile.mkdtemp(),"b.db")
br=BudgetRouter(db, {"P0":100,"P1":50,"P2":20}, absolute_cap=120)
ok("normal charge ok", br.charge("P1", 10)["lane_total"]==10)
ok("negative cost rejected", _fail(lambda: br.charge("P1", -5)))
ok("NaN cost rejected", _fail(lambda: br.charge("P1", float("nan"))))
ok("infinite cost rejected", _fail(lambda: br.charge("P1", float("inf"))))
ok("unknown lane rejected", _fail(lambda: br.charge("PX", 1)))
ok("lane cap enforced", _fail(lambda: br.charge("P2", 25)))   # P2 cap 20
# fill toward absolute cap: P0 90 + P1 already 10 = 100 ; +P0 25 -> 125 > 120 abs
br.charge("P0", 90)
ok("P0 within lane cap ok (total 100)", br.total_spent()==100)
# P1 lane has room (35<=50) but total would be 125 > 120 abs -> ABSOLUTE cap binds, even for reserved lanes
ok("no lane can punch absolute hard cap", _fail(lambda: br.charge("P1", 25)))
ok("charge up to absolute cap ok", br.charge("P1", 20)["grand_total"]==120)
ok("nothing beyond absolute cap", _fail(lambda: br.charge("P2", 1)))
# durable: reopen sees prior spend (not RAM)
br2=BudgetRouter(db, {"P0":100,"P1":50,"P2":20}, absolute_cap=120)
ok("durable spend survives reopen", br2.total_spent()==120)
ok("reopening ledger with inflated caps rejected",
   _fail(lambda: BudgetRouter(db,{"P0":1000,"P1":500,"P2":200},absolute_cap=1200)))

race_db=os.path.join(tempfile.mkdtemp(),"race.db")
BudgetRouter(race_db,{"lane":1.0},absolute_cap=1.0).close()
results=[]; lock=threading.Lock()
def worker():
    router=BudgetRouter(race_db,{"lane":1.0},absolute_cap=1.0)
    try: router.charge("lane",0.75); value="OK"
    except BudgetError: value="DENY"
    finally: router.close()
    with lock: results.append(value)
threads=[threading.Thread(target=worker) for _ in range(2)]
[t.start() for t in threads]; [t.join() for t in threads]
ok("concurrent reservations are atomic",sorted(results)==["DENY","OK"],str(results))
print(f"\nTALLY budget-router: PASS={P} FAIL={F}"); sys.exit(1 if F else 0)
