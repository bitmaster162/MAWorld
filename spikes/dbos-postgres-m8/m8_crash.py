import os, sys
from dbos import DBOS, SetWorkflowID
import m8_workflow as w
DBOS(config=w._config()); DBOS.launch()
idem = sys.argv[1]
os.environ["M8_CRASH"]="1"
with SetWorkflowID(w.wid(idem)):
    w.wf(idem)
print("crash-child: returned WITHOUT crashing?!"); sys.exit(0)
