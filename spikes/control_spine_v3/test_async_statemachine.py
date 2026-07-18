from async_task_registry import AsyncTaskRegistry, TaskBinding
R={}
reg=AsyncTaskRegistry(); b=TaskBinding("act-1","g-1","tr-1","tx-1"); reg.register(b)
R["orphan handle DENY"]=reg.poll(TaskBinding("act-1","g-1","tr-1","tx-X"))[0]=="DENY"
R["binding mismatch DENY"]=reg.poll(TaskBinding("act-2","g-1","tr-1","tx-1"))[0]=="DENY"
R["legit poll ALLOW"]=reg.poll(b)[0]=="ALLOW"
R["CREATED->RUNNING"]=reg.transition(b,"RUNNING")[0]=="ALLOW"
R["RUNNING->RESULT_READY"]=reg.transition(b,"RESULT_READY")[0]=="ALLOW"
R["skip to COMPLETED illegal"]=reg.transition(b,"COMPLETED")[0]=="DENY"
R["RESULT_READY->RESULT_FETCHED"]=reg.transition(b,"RESULT_FETCHED")[0]=="ALLOW"
R["RESULT_FETCHED->VERIFIED"]=reg.transition(b,"VERIFIED")[0]=="ALLOW"
R["VERIFIED->COMPLETED"]=reg.transition(b,"COMPLETED")[0]=="ALLOW"
R["terminal reopen DENY"]=reg.transition(b,"RUNNING")[0]=="DENY"
reg2=AsyncTaskRegistry(); bb=TaskBinding("a","g","t","h"); reg2.register(bb)
R["transition wrong trace DENY"]=reg2.transition(TaskBinding("a","g","tX","h"),"RUNNING")[0]=="DENY"
print("== AsyncTaskRegistry full state machine ==")
ok=True
for k,v in R.items(): print(("PASS" if v else "FAIL"),"|",k); ok=ok and v
print("\n"+("ALL PASS ("+str(sum(R.values()))+"/"+str(len(R))+")" if ok else "FAIL"))
import sys; sys.exit(0 if ok else 1)
