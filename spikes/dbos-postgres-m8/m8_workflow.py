import os, time, hashlib
from dbos import DBOS
PG = os.environ["M8_PG_URL"]
EFFECT_LOG = os.environ["M8_EFFECT_LOG"]
def _config(): return {"name":"m8-pg","system_database_url":PG}
@DBOS.step()
def step_effect(idem):
    # external effect (simulates a venue order). On recovery a COMPLETED step must NOT re-run.
    with open(EFFECT_LOG,"a") as f: f.write("EFFECT %s %f\n"%(idem,time.time()))
    return {"order_id": idem}
@DBOS.step()
def step_after(o):
    return {"done": o["order_id"]}
@DBOS.workflow()
def wf(idem):
    o = step_effect(idem)
    if os.environ.get("M8_CRASH")=="1":
        os._exit(137)   # hard crash AFTER the effect step is durably committed to Postgres
    return step_after(o)
def wid(idem): return "m8-"+hashlib.sha256(idem.encode()).hexdigest()[:16]
