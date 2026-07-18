import sys, os
from datetime import date
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT,"libs"))
from maworld_core.arena_frictions import (MarketMicro, almgren_chriss, round_trip, borrow_cost,
                                          settle_t1, limit_band, clamp_to_band)
P=F=0
def ok(n,c,d=""):
    global P,F; b=bool(c); P+=b; F+=(not b); print(("  PASS " if b else "  FAIL ")+n+("" if b else f" <- {d}"))

M = MarketMicro(adv=1000.0, sigma_daily=0.03)

# --- Almgren-Chriss: impact is quadratic in size (this is what kills 'max size' LLM proposals) ---
c1 = almgren_chriss(10, 100.0, M); c2 = almgren_chriss(20, 100.0, M)
imp1 = c1["permanent"]+c1["temporary"]; imp2 = c2["permanent"]+c2["temporary"]
ok("AC impact is superlinear: 2x size -> ~4x impact cost", 3.5 < (imp2/imp1) < 4.5, f"{imp2/imp1:.2f}x")
ok("AC cost in bps grows with participation", almgren_chriss(400,100.0,M)["bps"] > almgren_chriss(4,100.0,M)["bps"])
ok("AC reports participation vs ADV", abs(almgren_chriss(400,100.0,M)["participation"]-0.4) < 1e-9)
ok("zero qty -> zero cost", almgren_chriss(0,100.0,M)["total"]==0.0)
ok("fixed cost = (half-spread+fee) on notional", abs(almgren_chriss(1,100.0,M)["fixed"] - (1.0+2.0)/1e4*100.0) < 1e-9)
ok("AC exposes execution risk (variance term)", almgren_chriss(100,100.0,M)["risk_stdev"] > 0)

# --- the illusion of mid-price accounting ---
small = round_trip("BUY", 1, 100.0, 103.0, 100.0, M)
huge  = round_trip("BUY", 400, 100.0, 103.0, 100.0, M)
ok("small order keeps most of its gross", small["net"]/small["gross"] > 0.95, str(small))
ok("HUGE order (40% ADV) loses a large slice of gross to impact", huge["net"]/huge["gross"] < 0.60, str(huge))
ok("same edge, bigger size -> WORSE net per unit",
   (huge["net"]/400) < (small["net"]/1), f"{huge['net']/400:.3f} vs {small['net']:.3f}")

# --- shorts pay borrow; longs do not ---
b = borrow_cost(100, 100.0, M, days=30)
ok("short borrow accrues with time", b > 0 and borrow_cost(100,100.0,M,days=60) > b)
sh = round_trip("SELL", 100, 100.0, 97.0, 100.0, M, days_held=30)
lo = round_trip("BUY",  100, 100.0, 103.0, 100.0, M, days_held=30)
ok("short leg is charged borrow (worse net than mirror long)", sh["friction"] > lo["friction"], f"{sh['friction']} vs {lo['friction']}")
ok("profitable short still nets positive after costs", sh["net"] > 0, str(sh))

# --- limit-up / limit-down band ---
lo_b, hi_b = limit_band(100.0, M)
ok("limit band is +/-10% of prev close", (abs(lo_b-90)<1e-9 and abs(hi_b-110)<1e-9))
px, hit = clamp_to_band(130.0, 100.0, M)
ok("fill beyond limit-up is clamped to the band", abs(px-110)<1e-9 and hit)
lim = round_trip("BUY", 1, 100.0, 130.0, 100.0, M)
ok("round-trip flags limit_hit and cannot book the impossible price", lim["limit_hit"] and abs(lim["exit"]-110.0)<1e-6, str(lim))

# --- T+1 settlement, weekend-aware ---
ok("T+1 on a Wednesday -> Thursday", settle_t1(date(2026,7,15)) == date(2026,7,16))
ok("T+1 on a Friday skips the weekend -> Monday", settle_t1(date(2026,7,17)) == date(2026,7,20))
ok("round-trip reports a settlement date", round_trip("BUY",1,100.0,103.0,100.0,M,trade_day=date(2026,7,17))["settles"]=="2026-07-20")
ok("HOLD costs nothing and settles nothing", round_trip("HOLD",0,100.0,103.0,100.0,M)["net"]==0.0)

print(f"\nTALLY arena-frictions: PASS={P} FAIL={F}"); sys.exit(1 if F else 0)
