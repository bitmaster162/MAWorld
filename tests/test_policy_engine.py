import sys
from policy_engine import Policy, PolicyEngine
P=F=0
def ok(n,c,d=""):
    global P,F; b=bool(c); P+=b; F+=(not b); print(("  PASS " if b else "  FAIL ")+n+("" if b else f" <- {d}"))
pol=[
 Policy("PERMIT","orchestrator","venue.order","BINANCE:BTCUSDT", lambda c: c.get("risk_bps",1e9)<=100),
 Policy("FORBID","*","venue.order","*", lambda c: c.get("live") is True),   # never live via policy
 Policy("PERMIT","*","read","*"),
]
e=PolicyEngine(pol)
ok("permit when condition holds", e.evaluate("orchestrator","venue.order","BINANCE:BTCUSDT",{"risk_bps":50}).allow)
ok("deny when condition fails (risk>1%)", not e.evaluate("orchestrator","venue.order","BINANCE:BTCUSDT",{"risk_bps":250}).allow)
ok("FORBID overrides PERMIT (live blocked)", not e.evaluate("orchestrator","venue.order","BINANCE:BTCUSDT",{"risk_bps":50,"live":True}).allow)
ok("default-deny for unmatched action", not e.evaluate("orchestrator","canon.write","x").allow)
ok("permit read for anyone", e.evaluate("anybody","read","anything").allow)
ok("wrong principal -> default deny on order", not e.evaluate("stranger","venue.order","BINANCE:BTCUSDT",{"risk_bps":10}).allow)
print(f"\nTALLY policy-engine: PASS={P} FAIL={F}"); sys.exit(1 if F else 0)
