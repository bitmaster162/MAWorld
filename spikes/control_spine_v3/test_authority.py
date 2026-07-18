"""Tests for AsyncTaskRegistry (orphan-poll ban) + Capability tokens (report 06 acceptance)."""
from async_task_registry import AsyncTaskRegistry, TaskBinding
from capability import Authority

C=[]
def ck(name, cond): C.append((name, bool(cond)))

# ---- AsyncTaskRegistry ----
reg = AsyncTaskRegistry()
b = TaskBinding("act-1","grant-1","trace-1","task-ext-1")
reg.register(b)
# legit poll with full matching binding
ck("legit poll ALLOW", reg.poll(TaskBinding("act-1","grant-1","trace-1","task-ext-1"))[0]=="ALLOW")
# orphan: unknown handle
ck("unknown handle DENY", reg.poll(TaskBinding("act-1","grant-1","trace-1","task-ext-X"))[0]=="DENY")
# authority mismatch: same handle, different action_spec
ck("action mismatch DENY", reg.poll(TaskBinding("act-2","grant-1","trace-1","task-ext-1"))=="DENY" or reg.poll(TaskBinding("act-2","grant-1","trace-1","task-ext-1"))[0]=="DENY")
# authority mismatch: different trace
ck("trace mismatch DENY", reg.poll(TaskBinding("act-1","grant-1","trace-X","task-ext-1"))[0]=="DENY")
# different grant (re-issued authority)
ck("grant mismatch DENY", reg.poll(TaskBinding("act-1","grant-X","trace-1","task-ext-1"))[0]=="DENY")

# ---- Capability tokens ----
A = Authority(b"spike-secret")
g = A.issue_grant("projA","workload-1",{"repo.read","worktree.write","git.commit"}, ttl_sec=300)
# mint + redeem happy path
tok,r = A.mint_token(g,"act-100","projA","git.commit"); ck("mint ok", tok is not None)
ck("redeem ALLOW", A.redeem(tok,"act-100","git.commit")[0]=="ALLOW")
# one-time: reuse blocked
ck("token reuse DENY", A.redeem(tok,"act-100","git.commit")==("DENY","TOKEN_REUSE_BLOCKED"))
# cross-project blocked at mint
_,r2 = A.mint_token(g,"act-101","projB","git.commit"); ck("cross-project DENY", r2=="CROSS_PROJECT_BLOCKED")
# capability enlargement impossible
_,r3 = A.mint_token(g,"act-102","projA","git.push"); ck("enlarge DENY", r3=="CAPABILITY_NOT_IN_GRANT")
# action binding: token for act-200 can't be redeemed for act-999
tok2,_ = A.mint_token(g,"act-200","projA","git.commit")
ck("action-bound DENY", A.redeem(tok2,"act-999","git.commit")==("DENY","ACTION_MISMATCH"))
# expired grant rejected
import time
ge = A.issue_grant("projA","w",{"git.commit"}, ttl_sec=-1)
_,re = A.mint_token(ge,"act-300","projA","git.commit"); ck("expired grant DENY", re=="GRANT_EXPIRED")

print("== AsyncTaskRegistry + Capability tests ==")
p=0
for n,ok in C:
    print(("PASS" if ok else "FAIL"),"|",n); p+=ok
print(f"\n{p}/{len(C)} passed")
import sys; sys.exit(0 if p==len(C) else 1)
