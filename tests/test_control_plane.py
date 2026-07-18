import hashlib, hmac, os, sys, time, uuid, tempfile
from control_plane import (OwnerApprovalBoundary, OwnerBinding, WebhookReplayStore,
                           high_impact_execute)
from action_authority import (ActionSpec, ActionExecutor, ActionVerifier, DecisionIssuer,
                              HumanApprovalIssuer, SQLiteNonceStore)
P=F=0
def ok(n,c,d=""):
    global P,F; b=bool(c); P+=b; F+=(not b); print(("  PASS " if b else "  FAIL ")+n+("" if b else f" <- {d}"))

NOW=int(time.time()); OWNER=42; SEC="test-webhook-secret-32bytes-long"
def upd(chat,text,nonce=None,date=None,**extra):
    message={"chat":{"id":chat},"date":NOW if date is None else date,
             "nonce":nonce or uuid.uuid4().hex,"text":text}
    message.update(extra)
    return {"message":message}
def signer(key): return lambda msg:hmac.new(key,msg,hashlib.sha256).hexdigest()
def verifier(key): return lambda msg,sig:hmac.compare_digest(signer(key)(msg),sig)

tmp=tempfile.mkdtemp(); replay_path=os.path.join(tmp,"owner.db")
GK=b"gate-domain-test-key"; HK=b"owner-domain-test-key"
gate=DecisionIssuer("gate-main",signer(GK),clock=lambda:NOW)
approver=HumanApprovalIssuer("owner-main",signer(HK),clock=lambda:NOW)
authority=ActionVerifier({"gate-main":verifier(GK)},{"owner-main":verifier(HK)},clock=lambda:NOW)
order=ActionSpec("venue.order","BINANCE:BTCUSDT",("cid1","0.001"))
fired={"n":0}
def effect(spec): fired["n"]+=1; return "placed"
nonce_store=SQLiteNonceStore(os.path.join(tmp,"action.db"))
executor=ActionExecutor({"venue.order":effect},authority,nonce_store)
replay=WebhookReplayStore(replay_path)
boundary=OwnerApprovalBoundary(OwnerBinding(OWNER,SEC),replay,executor,gate,approver,clock=lambda:NOW)

r=boundary.execute(order,upd(OWNER,"APPROVE:"+order.hash()),SEC)
ok("fixed owner boundary executes exact signed action",r["executed"] and fired["n"]==1)
other=ActionSpec("venue.order","BINANCE:ETHUSDT",("cid2","9")); fired["n"]=0
r=boundary.execute(other,upd(OWNER,"APPROVE:"+order.hash()),SEC)
ok("approval for A cannot execute B",not r["executed"] and fired["n"]==0)
ok("non-owner rejected",not boundary.execute(order,upd(999,"APPROVE:"+order.hash()),SEC)["executed"])
ok("wrong webhook secret rejected",not boundary.execute(order,upd(OWNER,"APPROVE:"+order.hash()),"wrong")["executed"])
nonce=uuid.uuid4().hex
first=boundary.execute(order,upd(OWNER,"APPROVE:"+order.hash(),nonce=nonce),SEC)
second=boundary.execute(order,upd(OWNER,"APPROVE:"+order.hash(),nonce=nonce),SEC)
ok("durable owner nonce replay rejected",first["executed"] and not second["executed"])
ok("stale approval rejected",not boundary.execute(order,upd(OWNER,"APPROVE:"+order.hash(),date=NOW-9999),SEC)["executed"])
ok("future approval rejected",not boundary.execute(order,upd(OWNER,"APPROVE:"+order.hash(),date=NOW+9999),SEC)["executed"])
ok("malformed and oversized updates rejected",
   not boundary.execute(order,{"message":"bad"},SEC)["executed"] and
   not boundary.execute(order,upd(OWNER,"APPROVE:"+order.hash(),junk="x"*20000),SEC)["executed"])
persist_nonce=uuid.uuid4().hex
boundary.execute(order,upd(OWNER,"APPROVE:"+order.hash(),nonce=persist_nonce),SEC)
replay.close(); replay2=WebhookReplayStore(replay_path)
boundary2=OwnerApprovalBoundary(OwnerBinding(OWNER,SEC),replay2,executor,gate,approver,clock=lambda:NOW)
ok("replay remains rejected after replay-store restart",
   not boundary2.execute(order,upd(OWNER,"APPROVE:"+order.hash(),nonce=persist_nonce),SEC)["executed"])
try: high_impact_execute(order,executor,gate,approver,{},SEC,None,None); legacy=False
except TypeError: legacy=True
ok("legacy per-call trust composition is disabled",legacy)

replay2.close(); nonce_store.close()
print(f"\nTALLY control-plane: PASS={P} FAIL={F}"); sys.exit(1 if F else 0)
