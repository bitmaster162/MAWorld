import os, tempfile, threading, time
import hardened_effect_registry as R
P=F=0
def ok(n,c,d=""):
    global P,F; b=bool(c); P+=b; F+=(not b); print(("  PASS " if b else "  FAIL ")+n+("" if b else f" <- {d}"))

d=tempfile.mkdtemp(); path=os.path.join(d,"eff.db")
B1={"tenant":"tenant-a","action":"venue.order","payload":{"order":"X","qty_micros":1000}}
B2={"tenant":"tenant-a","action":"venue.order","payload":{"order":"Y","qty_micros":2000}}
B3={"tenant":"tenant-a","action":"venue.order","payload":{"order":"Z","qty_micros":3000}}

# 1) CONCURRENCY: 20 threads, same idem -> effect fires EXACTLY once
reg=R.HardenedEffectRegistry(path)
fires={"n":0}; lock=threading.Lock()
def do():
    with lock: fires["n"]+=1
    return {"order":"X"}
def worker(res,i):
    r=R.HardenedEffectRegistry(path)  # each thread its own connection (real concurrency)
    res[i]=r.execute_once("ORD-1", do, **B1); r.close()
res={}; ths=[threading.Thread(target=worker,args=(res,i)) for i in range(20)]
[t.start() for t in ths]; [t.join() for t in ths]
fired=[v for v in res.values() if v["status"]=="FIRED"]
replayed=[v for v in res.values() if v["status"] in ("REPLAYED_NO_REFIRE","IN_FLIGHT_HOLD")]
ok("concurrency: do_effect ran EXACTLY once", fires["n"]==1, f"n={fires['n']}")
ok("concurrency: exactly one FIRED", len(fired)==1, str([v['status'] for v in res.values()]))
ok("concurrency: registry fired_count==1", R.HardenedEffectRegistry(path).fired_count("ORD-1")==1)
ok("concurrency: others did NOT refire", len(replayed)==19 or (len(res)-1==len([v for v in res.values() if v['status']!='FIRED'])))

# 2) plain replay after confirm -> no refire
reg2=R.HardenedEffectRegistry(path)
before=reg2.fired_count("ORD-1")
r=reg2.execute_once("ORD-1", do, **B1)
ok("replay after CONFIRMED -> REPLAYED_NO_REFIRE", r["status"]=="REPLAYED_NO_REFIRE")
ok("replay did not increment fires", fires["n"]==1 and reg2.fired_count("ORD-1")==before)

# 3) CRASH WINDOW: effect SENT but not CONFIRMED (process died). Recovery must NOT refire.
reg3=R.HardenedEffectRegistry(path)
reg3.simulate_crash_after_send("ORD-2", **B2)
crash_fires={"n":0}
def do2():
    crash_fires["n"]+=1; return {"order":"Y"}
# no reconcile available -> must HOLD, never refire
r=reg3.execute_once("ORD-2", do2, **B2)
ok("crash-window: no reconcile -> HOLD (no refire)", r["status"]=="IN_FLIGHT_HOLD" and crash_fires["n"]==0)
# with reconcile that finds the effect DID happen -> confirm, still no refire
r=reg3.execute_once("ORD-2", do2, reconcile=lambda k: {"exists":True,"result":{"order":"Y"}}, **B2)
ok("crash-window: reconcile CONFIRMED, no refire", r["status"]=="RECONCILED_CONFIRMED" and crash_fires["n"]==0)

# 4) crash-window where provider says effect ABSENT -> hold (operator decides), still no auto-refire
reg4=R.HardenedEffectRegistry(path); reg4.simulate_crash_after_send("ORD-3", **B3)
r=reg4.execute_once("ORD-3", do2, reconcile=lambda k:{"exists":False}, **B3)
ok("crash-window: reconcile ABSENT -> HOLD, no auto-refire", r["status"]=="RECONCILE_ABSENT_HOLD" and crash_fires["n"]==0)

# 5) the same idempotency key cannot be reused for different tenant/action/payload work
collision_fires={"n":0}
def collision(): collision_fires["n"]+=1; return {"order":"ATTACK"}
try:
    reg2.execute_once("ORD-1", collision, tenant="tenant-b", action="payments.send",
                      payload={"amount_cents":999999})
    collision_blocked=False
except R.IdempotencyBindingConflict:
    collision_blocked=True
ok("idempotency key collision across work -> fail closed", collision_blocked and collision_fires["n"]==0)

import sys
print(f"\nTALLY effect-registry hardened: PASS={P} FAIL={F}")
sys.exit(1 if F else 0)
