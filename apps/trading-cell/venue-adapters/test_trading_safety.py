from decimal import Decimal
import trading_safety as T
from trading_safety import InstrumentSpec, RiskDecision, UnitError, RiskBlocked
P=F=0
def ok(n,c,d=""):
    global P,F; b=bool(c); P+=b; F+=(not b); print(("  PASS " if b else "  FAIL ")+n+("" if b else f" <- {d}"))
def rejects(n, fn):
    try: fn(); ok(n, False)
    except UnitError: ok(n, True)

btc = InstrumentSpec("BTCUSDT", qty_precision=3, price_precision=2,
                     lot_size=Decimal("0.001"), tick_size=Decimal("0.01"),
                     min_qty=Decimal("0.001"), max_qty=Decimal("100"))

class Intent:
    def __init__(self, qf, pf=0, cid="c1"): self.quantity_fixed=qf; self.price_fixed=pf; self.client_order_id=cid
class Venue:
    dry_run=True
    def __init__(self): self.calls=0
    def _submit_converted(self,p): self.calls+=1; return p

# THE core bug: fixed-point 1.0 == 1_000_000; must become qty 1.0, NOT 1000000
ok("fixed 1_000_000 -> 1.0 (not 1000000)", T.fixed_to_qty(1_000_000, btc)==Decimal("1.000"))
ok("fixed 500_000 -> 0.5", T.fixed_to_qty(500_000, btc)==Decimal("0.500"))
# lot rounding: 0.0015 -> 0.001 (round down to lot)
ok("lot rounding down 0.0015->0.001", T.fixed_to_qty(1_500, btc)==Decimal("0.001"))
# below min rejected
try: T.fixed_to_qty(500, btc); ok("below-min rejected",False)   # 0.0005 < min 0.001
except UnitError: ok("below-min qty rejected", True)
# above max rejected
try: T.fixed_to_qty(200_000_000, btc); ok("above-max rejected",False)  # 200 > max 100
except UnitError: ok("above-max qty rejected", True)
# non-int fixed rejected (someone passes a float/decimal by mistake)
try: T.fixed_to_qty(1.0, btc); ok("float qty rejected",False)
except UnitError: ok("non-int fixed-point rejected", True)
# price ticking
ok("price 50000.017 -> 50000.01 tick", T.fixed_to_price(50_000_017_000, btc)==Decimal("50000.01"))
ok("zero price is the explicit MARKET sentinel", T.fixed_to_price(0, btc)==Decimal("0"))

# Adversarial rounding: floor-to-step and precision formatting must never increase the raw input.
six_milli = InstrumentSpec("SIX", qty_precision=3, price_precision=3,
                           lot_size=Decimal("0.006"), tick_size=Decimal("0.006"),
                           min_qty=Decimal("0.006"), max_qty=Decimal("99.996"))
q_floor = T.fixed_to_qty(19_000, six_milli)
p_floor = T.fixed_to_price(19_000, six_milli)
ok("quantity floor 0.019 -> 0.018 never increases", q_floor==Decimal("0.018") and q_floor<=Decimal("0.019"))
ok("price floor 0.019 -> 0.018 never increases", p_floor==Decimal("0.018") and p_floor<=Decimal("0.019"))
ok("exact 0.018 lot multiple remains 0.018", T.fixed_to_qty(18_000, six_milli)==Decimal("0.018"))
rejects("lot 0.006 is rejected at qty precision 2",
        lambda: InstrumentSpec("BAD",2,2,Decimal("0.006"),Decimal("0.01"),Decimal("0.006"),Decimal("0.996")))
rejects("tick 0.006 is rejected at price precision 2",
        lambda: InstrumentSpec("BAD",3,2,Decimal("0.001"),Decimal("0.006"),Decimal("0.001"),Decimal("1.000")))

for label, bad in [("bool", True), ("float", 1.0), ("Decimal", Decimal("1")),
                   ("NaN", float("nan")), ("Infinity", float("inf")),
                   ("negative", -1), ("i64 overflow", 2**63)]:
    rejects(f"invalid quantity {label} rejected", lambda bad=bad: T.fixed_to_qty(bad, btc))
for label, bad in [("bool", True), ("float", 1.0), ("Decimal", Decimal("1")),
                   ("NaN", float("nan")), ("Infinity", float("inf")),
                   ("negative", -1), ("i64 overflow", 2**63)]:
    rejects(f"invalid price {label} rejected", lambda bad=bad: T.fixed_to_price(bad, btc))
rejects("positive price below one tick cannot become MARKET", lambda: T.fixed_to_price(1, btc))

def spec(**changes):
    values = dict(symbol="X", qty_precision=3, price_precision=2,
                  lot_size=Decimal("0.001"), tick_size=Decimal("0.01"),
                  min_qty=Decimal("0.001"), max_qty=Decimal("1.000"))
    values.update(changes)
    return InstrumentSpec(**values)
for label, changes in [
    ("zero lot", {"lot_size": Decimal("0")}),
    ("negative tick", {"tick_size": Decimal("-0.01")}),
    ("NaN lot", {"lot_size": Decimal("NaN")}),
    ("infinite tick", {"tick_size": Decimal("Infinity")}),
    ("negative min", {"min_qty": Decimal("-0.001")}),
    ("infinite max", {"max_qty": Decimal("Infinity")}),
    ("float lot", {"lot_size": 0.001}),
    ("bool precision", {"qty_precision": True}),
    ("negative precision", {"qty_precision": -1}),
    ("excessive precision", {"price_precision": 19}),
    ("fractional precision", {"price_precision": 2.0}),
    ("min off lot", {"min_qty": Decimal("0.0015")}),
    ("max off lot", {"max_qty": Decimal("1.0005")}),
    ("min above max", {"min_qty": Decimal("2.000"), "max_qty": Decimal("1.000")}),
]:
    rejects(f"invalid spec {label} rejected", lambda changes=changes: spec(**changes))

# RiskDecision is untrusted proposal metadata; safe_submit never invokes a venue.
v=Venue()
try: T.safe_submit(v, Intent(1_000_000), RiskDecision("DENY"), btc); ok("DENY blocks submit",False)
except RiskBlocked: ok("DENY blocks submit (no venue call)", True)
try: T.safe_submit(v, Intent(1_000_000), RiskDecision("REDUCE_ONLY"), btc); ok("REDUCE_ONLY blocks new order",False)
except RiskBlocked: ok("REDUCE_ONLY blocks new order", True)
try: T.safe_submit(v, Intent(1_000_000), "ALLOW", btc); ok("string risk rejected",False)
except RiskBlocked: ok("non-RiskDecision object rejected", True)
r=T.safe_submit(v, Intent(1_000_000), RiskDecision("ALLOW",50), btc)
ok("ALLOW returns converted proposal only",
   r["status"]=="PROPOSED" and r["payload"]["qty"]=="1.000" and
   r["submitted"] is False and r["authoritative"] is False and v.calls==0)

class ExplodingLiveVenue:
    dry_run=False
    def __init__(self): self.calls=0
    def _submit_converted(self,p): self.calls+=1; raise AssertionError("venue invoked")
class ExplodingRegistry:
    def __init__(self): self.calls=0
    def execute_once(self,*a,**k): self.calls+=1; raise AssertionError("registry invoked")
lv=ExplodingLiveVenue(); reg=ExplodingRegistry(); rec={"n":0}
def reconcile(_): rec["n"]+=1; raise AssertionError("reconcile invoked")
attack=T.safe_submit(lv, Intent(1_000_000,cid="attacker-1"), RiskDecision("ALLOW",50), btc,
                     effect_registry=reg, reconcile=reconcile, tenant="tenant-a")
ok("forged ALLOW cannot cross any effect boundary",
   attack["status"]=="PROPOSED" and not attack["submitted"] and
   lv.calls==0 and reg.calls==0 and rec["n"]==0)

import sys
print(f"\nTALLY trading-safety: PASS={P} FAIL={F}")
sys.exit(1 if F else 0)
