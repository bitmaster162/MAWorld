"""Arena bridge — Sovereign Arena / Battle of AI as a GOVERNED PRODUCT over the MAWorld spine.
Turns EXISTING modules toward the Arena (exactly like pfi_bridge / bitevo_bridge / reflex_bridge):
reuse, never duplicate. Nothing new is invented here — the Arena is the spine, pointed at a product.

Wiring (each requirement of a fair arena -> the module that already implements it):
  contestant identity / kill-switch .... agent_registry + agent_containment (global-kill, terminate)
  prompt-injection in rationale ........ input_guard
  anti-lookahead (entity anonymization). Snapshot(anonymized) + engine-private real symbol/date
  risk cap + units/lot/tick ............ trading_safety (RiskDecision, fixed_to_qty)
  completeness (no cherry-picking) ..... hermes_battle.arena_commit/arena_verify (commit-reveal+Merkle)
  tamper-evident bi-temporal audit ..... article12_export.ComplianceLog (hash-chain, EU AI Act Art.12)
  reliability -> autonomy/circuit-break. error_budget (ALERT->THROTTLE->FREEZE->CIRCUIT_BREAK)
  unified cross-frequency leaderboard .. Bradley-Terry (normalized per episode, from the DR pack)

Invariants (legal + architectural — both falsifiable in tests):
  * Contestants (Hermes/Nemotron-550, GPT, Claude, Grok, ...) are UNTRUSTED PROPOSERS, never authority.
  * PAPER ONLY. LIVE_TRADING_ENABLED is False: no broker-account linkage, no auto-trade, no real money.
    (US Publisher's Exclusion / Lowe v. SEC; EU MiFID II+MAR: auto-copying trades => unregistered adviser.)
  * Commit (root+count) is published BEFORE reveal -> a losing trade cannot be silently deleted.
"""
from __future__ import annotations
import time
from decimal import Decimal
from dataclasses import dataclass, field
from maworld_core.input_guard import admit_input
from maworld_core.trading_safety import RiskDecision, InstrumentSpec, fixed_to_qty
from maworld_core.article12_export import Article12Record, ComplianceLog
from maworld_core.error_budget import Budget, exhaustion_action
from maworld_core.hermes_battle import arena_commit, arena_verify, merkle_root   # reuse (single source)
from maworld_core.arena_frictions import MarketMicro, round_trip, almgren_chriss
from maworld_core import arena_scoring

RISK_CAP_BPS = 100              # arena rule: <=1% risk per trade
LIVE_TRADING_ENABLED = False    # HARD legal invariant: demo-show only, never live

class LiveTradingForbidden(RuntimeError): pass
class UnscoredArena(RuntimeError): pass

def assert_paper_only(link_broker_account: bool = False, auto_trade: bool = False):
    """Legal gate. Linking a user's broker account or auto-copying trades converts the product from a
    protected publisher/SaaS demo into portfolio management (MiFID II) / unregistered adviser (Weiss
    Research). Fail-closed, by construction."""
    if LIVE_TRADING_ENABLED or link_broker_account or auto_trade:
        raise LiveTradingForbidden("Arena is paper-only: no broker linkage, no auto-trade (US/EU)")
    return True

@dataclass
class Contestant:
    agent_id: str
    model: str                  # "nemotron-550/openrouter" | "glm-5.2" | "gpt-5.1" | ...
    display: str = ""

@dataclass
class Snapshot:
    """ANONYMIZED market snapshot — entity anonymization (anti-lookahead, from the DR pack).
    Contestants see asset_id + OHLCV only; the real symbol/date stay private to the engine, so a model
    cannot 'predict the past' from memorized training data."""
    asset_id: str
    ohlcv: tuple                # (open, high, low, close, volume) — anonymized, all a contestant sees
    spec: InstrumentSpec
    real_symbol: str = ""       # engine-private (never shown to contestants)
    real_date: str = ""         # engine-private
    micro: MarketMicro | None = None   # engine-private market model (impact/spread/borrow/limits)
    prev_close: float = 0.0     # engine-private, for the limit-up/down band
    @property
    def mid(self) -> float:
        return float(self.ohlcv[3]) if len(self.ohlcv) > 3 else 0.0

def anonymize(real_symbol: str, real_date: str, ohlcv, spec: InstrumentSpec, asset_id="ASSET_7",
              micro: MarketMicro | None = None, prev_close: float | None = None) -> Snapshot:
    o = tuple(ohlcv)
    return Snapshot(asset_id, o, spec, real_symbol, real_date, micro,
                    float(prev_close) if prev_close is not None else (float(o[3]) if len(o) > 3 else 0.0))

@dataclass
class ArenaProposal:
    """What a contestant PROPOSES. `claimed_pnl` is what the MODEL asserts it will make — untrusted,
    recorded as evidence, NEVER scored. The engine computes the real PnL in settle() after frictions
    ('an agent cannot accept its own work', applied to money)."""
    agent_id: str
    side: str                   # BUY | SELL | HOLD
    qty_fixed: int
    risk_bps: int
    rationale: str
    claimed_pnl: float = 0.0

class ArenaSession:
    def __init__(self, snapshot: Snapshot, containment, budget: Budget | None = None, log=None):
        assert_paper_only()
        self.snap = snapshot
        self.containment = containment
        self.budget = budget or Budget()
        self.log = log or ComplianceLog()
        self._trades: list[dict] = []
        self._blocked: list[dict] = []
        self._commitment: dict | None = None
        self._settled = False

    # ---- anti-lookahead -----------------------------------------------------
    def _lookahead(self, text: str):
        """Contestant must reason from the anonymized snapshot alone. Naming the real symbol or date
        proves out-of-band knowledge (memorization/leakage) -> block, per the DR anti-lookahead protocol."""
        t = (text or "").lower()
        for probe in filter(None, [self.snap.real_symbol, self.snap.real_date]):
            if probe.lower() in t:
                return probe
        return None

    # ---- the spine walk for one proposal ------------------------------------
    def submit(self, p: ArenaProposal) -> dict:
        adm = self.containment.admit(p.agent_id, write=True)         # kill-switch / terminated / shadow NHI
        if not adm.get("admit"):
            return self._block(p, "containment: " + str(adm.get("reason", "denied")))
        if not admit_input(p.rationale, source="external")["admit"]:  # untrusted proposer text
            return self._block(p, "input_guard: prompt-injection")
        probe = self._lookahead(p.rationale)
        if probe:
            return self._block(p, "lookahead: out-of-band reference '%s'" % probe)
        rd = RiskDecision("ALLOW", p.risk_bps) if p.risk_bps <= RISK_CAP_BPS else RiskDecision("DENY", p.risk_bps)
        if rd.kind != "ALLOW":
            return self._block(p, "risk>%dbps" % RISK_CAP_BPS)
        try:
            qty = fixed_to_qty(p.qty_fixed, self.snap.spec)
        except Exception as e:
            return self._block(p, "unit-safety: " + str(e)[:40])
        trade = {"seq": len(self._trades), "agent_id": p.agent_id, "asset": self.snap.asset_id,
                 "side": p.side, "qty": str(qty), "risk_bps": p.risk_bps,
                 "claimed_pnl": p.claimed_pnl,   # untrusted model assertion, evidence only
                 "pnl": None}                    # engine-authoritative, filled by settle()
        self._trades.append(trade)                                    # PAPER fill
        self._audit(p, "ALLOW", "paper-filled")
        self.budget.record(failed=False)
        return {"accepted": True, "trade": trade}

    def _block(self, p: ArenaProposal, reason: str) -> dict:
        self._blocked.append({"agent_id": p.agent_id, "reason": reason})
        self._audit(p, "DENY", reason)
        self.budget.record(failed=True)
        if exhaustion_action(self.budget) == "CIRCUIT_BREAK":         # runaway contestant -> kill-switch
            self.containment.global_kill()
        return {"accepted": False, "reason": reason}

    def _audit(self, p: ArenaProposal, decision: str, outcome: str):
        self.log.append(Article12Record(
            agent_id=p.agent_id, action="arena.trade." + p.side, event_time=time.time(),
            decision=decision, capability_ref="arena:paper-trade",
            risk_level=("HIGH" if p.risk_bps > RISK_CAP_BPS else "LOW"), outcome=outcome))

    # ---- settlement: the ENGINE computes PnL, after frictions ----------------
    @staticmethod
    def _decision_view(t: dict) -> dict:
        """The commitment binds the DECISION, not the outcome — so it stays stable across settlement
        while still making it impossible to add or drop a trade after seeing the price move."""
        return {k: t[k] for k in ("seq", "agent_id", "asset", "side", "qty", "risk_bps")}

    def settle(self, exit_mid: float, days_held: float = 1.0) -> dict:
        """Reveal the exit price and compute engine-authoritative PnL for every trade, AFTER
        Almgren-Chriss impact, spread, fees, short borrow, limit bands and T+1 settlement."""
        if self.snap.micro is None:
            raise UnscoredArena("no market model on the snapshot: cannot compute honest PnL")
        for t in self._trades:
            r = round_trip(t["side"], float(t["qty"]), self.snap.mid, float(exit_mid),
                           self.snap.prev_close, self.snap.micro, days_held=days_held)
            t.update({"pnl": r["net"], "gross": r["gross"], "friction": r["friction"],
                      "impact_bps": r["impact_bps"], "limit_hit": r["limit_hit"], "settles": r["settles"]})
        self._settled = True
        return {"settled": len(self._trades), "exit": float(exit_mid)}

    def claim_divergence(self) -> list:
        """Where the model's self-reported PnL diverges from the engine's. Pure evidence: a contestant
        that claims +500 on a trade the engine settles at -12 is exposed by construction."""
        return [{"agent_id": t["agent_id"], "seq": t["seq"], "claimed": t["claimed_pnl"],
                 "engine": t["pnl"], "delta": (round(t["claimed_pnl"] - t["pnl"], 4)
                                               if t["pnl"] is not None else None)}
                for t in self._trades if t["pnl"] is None or abs(t["claimed_pnl"] - t["pnl"]) > 1e-9]

    # ---- commit-reveal: completeness proof (cannot cherry-pick) --------------
    def commit(self) -> dict:
        """Publish (merkle_root, count) over the DECISIONS, BEFORE the exit price is revealed."""
        self._commitment = arena_commit([self._decision_view(t) for t in self._trades])
        return dict(self._commitment)

    def reveal(self, published=None) -> dict:
        """Verify the published set against the commitment: any dropped/altered trade is detected."""
        src = self._trades if published is None else published
        return arena_verify([self._decision_view(t) for t in src], self._commitment)

    def tamper_evident(self) -> bool:
        return self.log.verify()

    def status(self) -> dict:
        return {"trades": len(self._trades), "blocked": len(self._blocked), "settled": self._settled,
                "burn_rate": self.budget.burn_rate(), "action": exhaustion_action(self.budget),
                "tamper_evident": self.tamper_evident()}

    # ---- leaderboard: Bradley-Terry, normalized per episode ------------------
    def leaderboard(self, min_publish: int = arena_scoring.MIN_EPISODES_PUBLISH,
                    min_rank: int = arena_scoring.MIN_EPISODES_PROVISIONAL) -> dict:
        """Delegates to arena_scoring (single source). The v1 leaderboard here was REFUTED: pairwise
        Bradley-Terry over raw mean-PnL let one lucky trade at n=1 outrank a steady agent at n=100 —
        and our own test asserted that flaw as if it were a feature. Now: episode utilities, shrinkage
        toward the grand mean, bootstrap CIs, no ranking below min_rank, and NO winner declared below
        min_publish or with overlapping CIs. Scores ENGINE pnl only; claimed_pnl never reaches it."""
        if not self._settled:
            raise UnscoredArena("settle() first: refusing to rank on contestant-claimed PnL")
        by: dict[str, list] = {}
        for t in self._trades:
            by.setdefault(t["agent_id"], []).append(t["pnl"])
        return arena_scoring.leaderboard(by, min_publish=min_publish, min_rank=min_rank)
