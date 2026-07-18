import os, sys
from dbos import DBOS, SetWorkflowID
import workflow as wf
def main():
    phase, idem = sys.argv[1], sys.argv[2]
    DBOS(config=wf._config()); DBOS.launch()
    wid = wf.make_workflow_id(idem)
    if phase == "crash":
        with SetWorkflowID(wid):
            wf.spine_workflow("npm test","orchestrator",idem)
        print("child(crash): finished WITHOUT crash?!"); sys.exit(0)
    handles = DBOS._recover_pending_workflows(["local"])
    print("child(recover): recovered", len(handles), "workflow(s)")
    for h in handles:
        try: h.get_result()
        except Exception as e: print("child(recover): result:", e)
    sys.exit(0)
if __name__ == "__main__": main()
