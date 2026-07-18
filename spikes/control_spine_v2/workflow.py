from __future__ import annotations
import os, json, hashlib, time
from dbos import DBOS, DBOSConfig
from gate_bridge import ControlSpineGate
from sandbox import run_python
from effect_registry import EffectRegistry
from mcp_preflight import normalize_mcp

STATE_DIR = os.environ.get("SPIKE_STATE", os.path.join(os.path.dirname(__file__), "_state"))
os.makedirs(STATE_DIR, exist_ok=True)
LEDGER_PATH = os.path.join(STATE_DIR, "audit_ledger.db")
EFFECT_PATH = os.path.join(STATE_DIR, "effect_registry.db")
DBOS_SYS = "sqlite:///" + os.path.join(STATE_DIR, "dbos_sys.db").replace("\\","/")
_gate = ControlSpineGate(LEDGER_PATH)
# restrictiveness order (least -> most). HOLD/DENY MUST dominate REQUIRE_CONFIRMATION so an
# MCP HOLD is never downgraded to an executable state by a policy REQUIRE_CONFIRMATION.
_ORDER = ["ALLOW","WARN","REQUIRE_CONFIRMATION","HOLD","DENY"]
def _stricter(a,b): return a if _ORDER.index(a)>=_ORDER.index(b) else b
_EXEC = ("ALLOW","WARN","REQUIRE_CONFIRMATION")

def _config() -> DBOSConfig:
    return {"name":"control-spine-v2","system_database_url":DBOS_SYS}

@DBOS.step()
def step_plan(command, agent):
    h = _gate.audit("workflow.plan", {"command":command,"agent":agent})
    return {"command":command,"agent":agent,"plan_hash":h}

@DBOS.step()
def step_mcp_gate(command, agent, mcp_meta):
    mcp = normalize_mcp(mcp_meta)
    _gate.audit("workflow.mcp_normalize", {"decision":mcp.decision,"reasons":mcp.reasons,"block":mcp.block})
    if mcp.decision == "DENY":
        return {"decision":"DENY","may_execute":False,"reasons":mcp.reasons,"stage":"mcp"}
    pol = _gate.check(tool="http", command=command, agent=agent)
    final = _stricter(mcp.decision, pol.decision)
    reasons = list(mcp.reasons) + list(pol.reasons)
    return {"decision":final,"may_execute":final in _EXEC,"reasons":reasons,
            "stage":"policy","mcp_block":mcp.block,"ledger_hash":pol.ledger_hash}

@DBOS.step()
def step_external_effect(command, idem_key):
    reg = EffectRegistry(EFFECT_PATH)
    try:
        def do_effect():
            open(os.path.join(STATE_DIR,"calls.log"),"a").write("CALL %s @ %f\n"%(idem_key,time.time()))
            return {"call_id":idem_key,"endpoint":"api.testnet.local"}
        out = reg.fire_once(idem_key,"mcp_tool","COMPENSATABLE",do_effect)
        _gate.audit("workflow.external_effect", {"idem_key":idem_key,"status":out["status"]})
        return out
    finally:
        reg.close()

@DBOS.step()
def step_verify(result):
    code = ("import json\no=json.loads(%s)\nassert o['endpoint']=='api.testnet.local'\nprint('VERIFY_OK')\n"
            % json.dumps(json.dumps(result)))
    res = run_python(code)
    _gate.audit("workflow.verify", {"ok":res.ok,"mechanism":res.mechanism})
    return {"ok":res.ok,"mechanism":res.mechanism}

@DBOS.workflow()
def spine_workflow(command, agent, idem_key, mcp_meta):
    step_plan(command, agent)
    gate = step_mcp_gate(command, agent, mcp_meta)
    if not gate["may_execute"]:
        _gate.audit("workflow.blocked", {"command":command,"decision":gate["decision"],"stage":gate.get("stage"),"reasons":gate["reasons"]})
        return {"status":"BLOCKED","decision":gate["decision"],"stage":gate.get("stage"),"reasons":gate["reasons"],"effect_fired":False}
    effect = step_external_effect(command, idem_key)
    verify = step_verify(effect["result"])
    _gate.audit("workflow.complete", {"idem_key":idem_key,"verify_ok":verify["ok"]})
    return {"status":"COMPLETED","decision":gate["decision"],"effect_fired":effect["status"]=="FIRED","verify":verify}

def make_workflow_id(idem_key):
    return "spine2-" + hashlib.sha256(idem_key.encode()).hexdigest()[:16]
