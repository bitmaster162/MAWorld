import os, sys, time, tempfile
from capability import mint_capability, verify_capability, safe_path
P=F=0
def ok(n,c,d=""):
    global P,F; b=bool(c); P+=b; F+=(not b); print(("  PASS " if b else "  FAIL ")+n+("" if b else f" <- {d}"))
KEY=b"cap-key"
tok=mint_capability(KEY,"agentX","venue.order","BINANCE:BTCUSDT",time.time()+300)
ok("valid capability verifies", verify_capability(KEY,tok,"agentX","venue.order","BINANCE:BTCUSDT"))
ok("bare string is NOT a capability", not verify_capability(KEY,"cap-123","agentX","venue.order","BINANCE:BTCUSDT"))
ok("wrong subject rejected", not verify_capability(KEY,tok,"other","venue.order","BINANCE:BTCUSDT"))
ok("wrong action rejected", not verify_capability(KEY,tok,"agentX","canon.write","BINANCE:BTCUSDT"))
ok("wrong resource rejected", not verify_capability(KEY,tok,"agentX","venue.order","BINANCE:ETHUSDT"))
exp=mint_capability(KEY,"agentX","venue.order","BINANCE:BTCUSDT",time.time()-1)
ok("expired capability rejected", not verify_capability(KEY,exp,"agentX","venue.order","BINANCE:BTCUSDT"))
ok("forged signature rejected", not verify_capability(KEY,tok[:-3]+"000","agentX","venue.order","BINANCE:BTCUSDT"))
# path guard: realpath containment
root=tempfile.mkdtemp(); sub=os.path.join(root,"out"); os.makedirs(sub)
ok("path inside allowed root ok", safe_path(os.path.join(sub,"f.txt"),[root]).startswith(os.path.realpath(root)))
try: safe_path("/etc/passwd",[root]); ok("outside root rejected",False)
except PermissionError: ok("path outside root rejected", True)
try: safe_path(os.path.join(sub,"..","..","etc","x"),[sub]); ok("traversal escape rejected",False)
except PermissionError: ok("'..' traversal escape rejected", True)
# prefix trick: /tmp/rootEVIL should NOT pass for allowed /tmp/root
sib=root+"EVIL"; os.makedirs(sib,exist_ok=True)
try: safe_path(os.path.join(sib,"x"),[root]); ok("prefix-sibling trick rejected",False)
except PermissionError: ok("prefix-sibling (rootEVIL vs root) rejected", True)
print(f"\nTALLY capability: PASS={P} FAIL={F}"); sys.exit(1 if F else 0)
