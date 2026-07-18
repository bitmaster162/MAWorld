from __future__ import annotations
import time, uuid
from dbos import DBOS, SetWorkflowID
from telegram_ingress import OwnerBinding, ReplayGuard, verify_update
import workflow as wf
def _upd(command):
    return {"message":{"chat":{"id":42},"date":time.time(),"nonce":uuid.uuid4().hex,"text":command}}
def main():
    binding = OwnerBinding(owner_chat_id=42, webhook_secret="s3cr3t-token")
    guard = ReplayGuard()
    DBOS(config=wf._config()); DBOS.launch()
    print("="*60); print("SPIKE: control spine v0 -- happy path"); print("="*60)
    ok,reason = verify_update(_upd("npm test"),"WRONG",binding,guard)
    print("[ingress] bad secret_token    -> ok=%s (%s)"%(ok,reason)); assert not ok
    upd = _upd("npm test"); ok,reason = verify_update(upd,"s3cr3t-token",binding,guard)
    print("[ingress] valid owner request -> ok=%s (%s)"%(ok,reason)); assert ok
    idem = "order-"+uuid.uuid4().hex[:8]
    with SetWorkflowID(wf.make_workflow_id(idem)):
        res = wf.spine_workflow("npm test","orchestrator",idem)
    print("[workflow] ALLOW -> %s, effect_fired=%s, verify=%s"%(res["status"],res.get("effect_fired"),res.get("verify",{}).get("mechanism")))
    assert res["status"]=="COMPLETED" and res["effect_fired"]
    idem2 = "order-"+uuid.uuid4().hex[:8]
    with SetWorkflowID(wf.make_workflow_id(idem2)):
        res2 = wf.spine_workflow("rm -rf /","orchestrator",idem2)
    print("[workflow] DENY  -> %s, decision=%s, effect_fired=%s"%(res2["status"],res2["decision"],res2["effect_fired"]))
    assert res2["status"]=="BLOCKED" and not res2["effect_fired"]
    print("[audit] ledger.verify() ->", wf._gate.verify_chain())
    print("\nHAPPY PATH OK -- gate ALLOW executed, DENY blocked before side effect, audit intact.")
if __name__=="__main__": main()
