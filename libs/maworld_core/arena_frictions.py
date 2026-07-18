"""Arena market frictions — the engine, not the contestant, decides what a trade actually cost.

Why this module exists (honest gap closed): the arena previously scored a contestant on the PnL the
contestant CLAIMED, on mid prices, with no market impact. That is (a) 'an agent accepting its own work'
applied to money, and (b) exactly what quants reject about LLM-trading demos. Here the engine computes
the fill and the PnL from a market model. A contestant's claimed_pnl is recorded as evidence and NEVER
scored.

Implements (per the DR pack's methodology requirements):
  * Almgren-Chriss expected implementation shortfall: permanent + temporary impact + fixed cost.
  * Bid/ask crossing (half-spread) + fees.
  * Short borrow cost (carry on the short leg).
  * T+1 settlement: proceeds are not spendable until the next business day.
  * limit-up / limit-down: a fill cannot happen beyond the daily limit band.
"""
from __future__ import annotations
import math
from dataclasses import dataclass
from datetime import date, timedelta

@dataclass
class MarketMicro:
    """Microstructure of the traded asset. Coefficients follow Almgren-Chriss normalized by ADV and
    daily volatility (the standard calibration: impact scales with sigma*price/ADV)."""
    adv: float                     # average daily volume (units)
    sigma_daily: float             # daily volatility as a fraction (0.03 = 3%)
    half_spread_bps: float = 1.0   # half the quoted spread
    fee_bps: float = 2.0           # exchange/broker fee per side
    gamma_coeff: float = 0.1       # permanent impact coefficient
    eta_coeff: float = 0.5         # temporary impact coefficient
    borrow_bps_annual: float = 300.0   # short borrow rate
    limit_pct: float = 0.10        # daily limit-up/down band vs previous close

class LimitBandBreached(RuntimeError): pass

def almgren_chriss(qty: float, price: float, micro: MarketMicro, horizon_days: float = 1.0,
                   slices: int = 10) -> dict:
    """Expected implementation shortfall (Almgren-Chriss 2000/2001).
      permanent  = 0.5 * gamma * X^2
      temporary  = (eta - 0.5*gamma*tau) * X^2 / T
      fixed      = (half_spread + fee) * price * |X|
    gamma/eta normalized as coeff * sigma * price / ADV, so impact grows with size-vs-liquidity.
    Returns absolute cost (currency) and cost in bps of notional. Quadratic in X: doubling the order
    roughly quadruples the impact cost — this is what kills naive 'max size' LLM proposals."""
    X = abs(float(qty))
    if X == 0:
        return {"permanent": 0.0, "temporary": 0.0, "fixed": 0.0, "total": 0.0, "bps": 0.0,
                "participation": 0.0, "risk_stdev": 0.0}
    T = max(1e-9, float(horizon_days))
    tau = T / max(1, int(slices))
    gamma = micro.gamma_coeff * micro.sigma_daily * price / max(1e-9, micro.adv)
    eta   = micro.eta_coeff   * micro.sigma_daily * price / max(1e-9, micro.adv)
    permanent = 0.5 * gamma * X * X
    temporary = max(0.0, (eta - 0.5 * gamma * tau)) * X * X / T
    fixed = (micro.half_spread_bps + micro.fee_bps) / 1e4 * price * X
    total = permanent + temporary + fixed
    notional = price * X
    # execution risk of the trajectory (AC variance term, uniform schedule)
    risk_stdev = micro.sigma_daily * price * X * math.sqrt(T / 3.0)
    return {"permanent": permanent, "temporary": temporary, "fixed": fixed, "total": total,
            "bps": (total / notional * 1e4) if notional else 0.0,
            "participation": X / max(1e-9, micro.adv), "risk_stdev": risk_stdev}

def limit_band(prev_close: float, micro: MarketMicro) -> tuple:
    """Daily limit-up / limit-down band. Fills outside the band are impossible."""
    return (prev_close * (1 - micro.limit_pct), prev_close * (1 + micro.limit_pct))

def clamp_to_band(price: float, prev_close: float, micro: MarketMicro) -> tuple:
    lo, hi = limit_band(prev_close, micro)
    if price < lo: return lo, True
    if price > hi: return hi, True
    return price, False

def borrow_cost(qty: float, price: float, micro: MarketMicro, days: float) -> float:
    """Carry on a short position. Longs pay nothing here."""
    return abs(float(qty)) * price * (micro.borrow_bps_annual / 1e4) * (days / 365.0)

def settle_t1(trade_day: date) -> date:
    """T+1 settlement, skipping weekends. Proceeds are not spendable before this date."""
    d = trade_day + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d

def round_trip(side: str, qty: float, entry_mid: float, exit_mid: float, prev_close: float,
               micro: MarketMicro, days_held: float = 1.0, trade_day: date | None = None) -> dict:
    """Engine-authoritative PnL for one paper round-trip, AFTER all frictions.

    Fills are clamped into the limit band; impact is charged on BOTH legs (entry and exit); shorts pay
    borrow. Returns gross (naive, mid-to-mid) and net (what actually happened) so the arena can show
    exactly how much of a 'winning' LLM trade was an illusion of frictionless mid-price accounting."""
    side = side.upper()
    if side == "HOLD" or qty == 0:
        return {"side": side, "qty": 0.0, "gross": 0.0, "net": 0.0, "friction": 0.0,
                "limit_hit": False, "settles": None, "impact_bps": 0.0}
    sign = 1.0 if side == "BUY" else -1.0
    entry_px, e_hit = clamp_to_band(entry_mid, prev_close, micro)
    exit_px,  x_hit = clamp_to_band(exit_mid,  prev_close, micro)
    ac_in  = almgren_chriss(qty, entry_px, micro, horizon_days=1.0)
    ac_out = almgren_chriss(qty, exit_px,  micro, horizon_days=1.0)
    gross = (exit_px - entry_px) * qty * sign                    # naive mid-to-mid (the illusion)
    friction = ac_in["total"] + ac_out["total"]
    if sign < 0:
        friction += borrow_cost(qty, entry_px, micro, days_held)
    net = gross - friction
    td = trade_day or date.today()
    return {"side": side, "qty": float(qty), "entry": entry_px, "exit": exit_px,
            "gross": round(gross, 4), "friction": round(friction, 4), "net": round(net, 4),
            "limit_hit": bool(e_hit or x_hit), "settles": settle_t1(td).isoformat(),
            "impact_bps": round(ac_in["bps"] + ac_out["bps"], 2),
            "participation": round(ac_in["participation"], 4)}
