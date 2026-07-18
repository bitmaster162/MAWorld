import os, sys
from dbos import DBOS
import m8_workflow as w
DBOS(config=w._config()); DBOS.launch()
handles = DBOS._recover_pending_workflows(["local"])
print("recover-child: recovered", len(handles), "workflow(s)")
for h in handles:
    try: print("recover-child: result", h.get_result())
    except Exception as e: print("recover-child: err", e)
sys.exit(0)
