from __future__ import annotations
import os, json, hashlib, time
from dbos import DBOS, DBOSConfig
from gate_bridge import ControlSpineGate
from sandbox import run_python
from effect_registry import EffectRegistry
STATE_DIR = os.environ.get("SPIKE_STATE", os.path.join(os.path.dirname(__file__), "_state"))
os.makedirs(STATE_DIR, exist_ok=True)
LEDGER_PATH = os.path.join(STATE_DIR, "audit_ledger.db")
EFFECT_PATH = os.path.join(STATE_DIR, "effect_registry.db")
DBOS_SYS = "sqlite:///" + os.path.join(STATE_DIR, "dbos_sys.db").replace("\\","/")
_gate = ControlSpineGate(LEDGER_PATH)
def _config() -> DBOSConfig:
    return {"name":"control-spine-v0","system_database_url":DBOS_SYS}
@DBOS.step()
def step_plan(command, agent):
    h = _gate.audit("workflow.plan", {"command":command,"agent":agent})
    return {"command":command,"agent":agent,"plan_hash":h}
@DBOS.step()
def step_gate(command, agent):
    r = _gate.check(tool="shell", command=command, agent=agent)
    return {"decision":r.decision,"may_execute":r.may_execute,"reasons":r.reasons,"ledger_hash":r.ledger_hash}
@DBOS.step()
def step_external_effect(command, idem_key):
    reg = EffectRegistry(EFFECT_PATH)
    try:
        def do_effect():
            open(os.path.join(STATE_DIR,"orders.log"),"a").write("ORDER %s @ %f\n"%(idem_key,time.time()))
            return {"order_id":idem_key,"venue":"SIMULATED_TESTNET"}
        out = reg.fire_once(idem_key,"sim_venue","COMPENSATABLE",do_effect)
        _gate.audit("workflow.external_effect", {"idem_key":idem_key,"status":out["status"]})
        return out
    finally:
        reg.close()
@DBOS.step()
def step_sandbox_verify(order):
    code = ("import json\no=json.loads(%s)\nassert o['venue']=='SIMULATED_TESTNET'\nprint('VERIFY_OK',o['order_id'])\n" % json.dumps(json.dumps(order)))
    res = run_python(code)
    _gate.audit("workflow.verify", {"ok":res.ok,"mechanism":res.mechanism,"egress_blocked":res.egress_blocked})
    return {"ok":res.ok,"mechanism":res.mechanism,"stdout":res.stdout.strip()}
@DBOS.workflow()
def spine_workflow(command, agent, idem_key):
    plan = step_plan(command, agent)
    gate = step_gate(command, agent)
    if not gate["may_execute"]:
        _gate.audit("workflow.blocked", {"command":command,"decision":gate["decision"]})
        return {"status":"BLOCKED","decision":gate["decision"],"effect_fired":False}
    effect = step_external_effect(command, idem_key)
    if os.environ.get("CRASH_AFTER_EFFECT") == "1":
        os.environ["CRASH_AFTER_EFFECT"] = "0"
        _gate.audit("workflow.CRASH_INJECTED", {"idem_key":idem_key})
        os._exit(137)
    verify = step_sandbox_verify(effect["result"])
    _gate.audit("workflow.complete", {"idem_key":idem_key,"verify_ok":verify["ok"]})
    return {"status":"COMPLETED","decision":gate["decision"],"effect_fired":effect["status"]=="FIRED","verify":verify}
def make_workflow_id(idem_key):
    return "spine-" + hashlib.sha256(idem_key.encode()).hexdigest()[:16]
