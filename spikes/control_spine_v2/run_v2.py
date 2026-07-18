"""End-to-end: 3 scenarios proving MCP normalizer врезан in the workflow before side effects."""
from __future__ import annotations
import uuid
from dbos import DBOS, SetWorkflowID
import workflow as wf

def good_mcp(**o):
    m = {"headers":{"mcp-protocol-version":"2025-11-25","origin":"https://localhost"},
         "transport":"streamable_http","allowed_origins":["https://localhost"],
         "oauth":{"resource_server_uri":"https://tool.local","token_audience":"https://tool.local"},
         "task":{"state":"none"}}
    m.update(o); return m

def main():
    DBOS(config=wf._config()); DBOS.launch()
    print("="*64); print("CONTROL SPINE v2: MCP normalizer in the workflow"); print("="*64)

    # 1. valid MCP 2025-11-25 + allowed policy -> COMPLETED, effect fires
    idem="call-"+uuid.uuid4().hex[:8]
    with SetWorkflowID(wf.make_workflow_id(idem)):
        r=wf.spine_workflow("egress GET api.testnet.local","orchestrator",idem,good_mcp())
    print("[1] valid MCP -> %s effect_fired=%s"%(r["status"],r.get("effect_fired")))
    assert r["status"]=="COMPLETED" and r["effect_fired"]

    # 2. spoofed MCP header -> DENY at MCP stage, NO side effect
    idem2="call-"+uuid.uuid4().hex[:8]
    with SetWorkflowID(wf.make_workflow_id(idem2)):
        r2=wf.spine_workflow("egress GET api.testnet.local","orchestrator",idem2,
                             good_mcp(headers={"mcp-protocol-version":"2025-11-25","origin":"https://localhost","mcp-evil":"x"}))
    print("[2] spoofed MCP header -> %s stage=%s effect_fired=%s"%(r2["status"],r2.get("stage"),r2["effect_fired"]))
    assert r2["status"]=="BLOCKED" and r2.get("stage")=="mcp" and not r2["effect_fired"]

    # 3. RC 2026-07-28 -> HOLD (not may_execute), NO side effect
    idem3="call-"+uuid.uuid4().hex[:8]
    with SetWorkflowID(wf.make_workflow_id(idem3)):
        r3=wf.spine_workflow("egress GET api.testnet.local","orchestrator",idem3,
                             good_mcp(headers={"mcp-protocol-version":"2026-07-28","origin":"https://localhost"}))
    print("[3] RC 2026-07-28 -> %s decision=%s effect_fired=%s"%(r3["status"],r3["decision"],r3["effect_fired"]))
    assert r3["status"]=="BLOCKED" and r3["decision"]=="HOLD" and not r3["effect_fired"]

    print("[audit]", wf._gate.verify_chain())
    print("\nV2 PASSED -- MCP normalize precedes gate; DENY/HOLD block before side effect.")

if __name__=="__main__": main()
