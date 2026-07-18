//! Trading Cell RiskService (D5 / closure §9): a deterministic, proposal-only risk filter.
//! It cannot authorize execution or a risk increase. Money is fixed-point (i64 scaled) — never f64.
//! An LLM SignalProposal is UNTRUSTED input: its `conviction_score` is IGNORED by risk math.
//!
//! Locally configured proposal limits:
//!   - max total drawdown 10% from equity peak (HARD STOP)
//!   - <= 20 trades per day
//!   - 3 consecutive losses -> 1h pause
//!   - risk per trade <= 1% of equity
//!
//! Kill-switches: stale market data (>100ms), reconciliation mismatch, strategy heartbeat loss
//! (deny). Fail-closed: any doubt -> DENY.
//! An `EligibleProposal` still requires an independent signed authority decision before execution.

pub const SCALE: i64 = 1_000_000; // fixed-point scale for money & fractions (1.0 == SCALE)

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Side {
    Buy,
    Sell,
}

/// Untrusted proposal from the (off-hot-path) LLM synthesizer.
#[derive(Debug, Clone)]
pub struct SignalProposal {
    pub instrument: String,
    pub side: Side,
    pub conviction_score: u8, // 0-100 — IGNORED by risk math (kept only for audit)
    pub proposed_risk_bps: u32, // basis points of equity to risk (1 = 0.01%)
    pub reduce_only: bool,
}

#[derive(Debug, Clone)]
pub struct RiskConfig {
    pub max_drawdown_bps: u32,       // 1000 = 10%
    pub max_trades_per_day: u32,     // 20
    pub max_consecutive_losses: u32, // 3
    pub max_risk_per_trade_bps: u32, // 100 = 1%
    pub max_tick_age_ms: u64,        // 100
}
impl Default for RiskConfig {
    fn default() -> Self {
        Self {
            max_drawdown_bps: 1000,
            max_trades_per_day: 20,
            max_consecutive_losses: 3,
            max_risk_per_trade_bps: 100,
            max_tick_age_ms: 100,
        }
    }
}

#[derive(Debug, Clone)]
pub struct RiskState {
    pub equity_fixed: i64,      // current equity (fixed-point)
    pub equity_peak_fixed: i64, // high-water mark
    pub trades_today: u32,
    pub consecutive_losses: u32,
    pub paused_until_ms: u64, // wall clock ms; 0 = not paused
    pub last_tick_ms: u64,
    pub reconciled: bool, // caller-supplied observation; never execution authority
    pub heartbeat_ok: bool, // caller-supplied observation; never execution authority
}

/// A proposal assessment only. No variant authorizes order submission or any side effect.
#[derive(Debug, PartialEq, Eq)]
pub enum RiskDecision {
    EligibleProposal { risk_bps: u32 },
    ReduceOnlyProposal { reason: &'static str },
    Deny { reason: &'static str },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PositionSizeError {
    NonPositiveEquity,
    ZeroRisk,
    RiskBpsOutOfRange,
    NonPositiveStopDistance,
    QuantityOutOfRange,
}

/// Evaluate proposal eligibility. Deterministic, no I/O, no LLM, and no execution authority.
pub fn evaluate_proposal(
    sig: &SignalProposal,
    cfg: &RiskConfig,
    st: &RiskState,
    now_ms: u64,
) -> RiskDecision {
    if cfg.max_drawdown_bps == 0
        || cfg.max_drawdown_bps > 10_000
        || cfg.max_trades_per_day == 0
        || cfg.max_consecutive_losses == 0
        || cfg.max_risk_per_trade_bps == 0
        || cfg.max_risk_per_trade_bps > 10_000
        || cfg.max_tick_age_ms == 0
    {
        return RiskDecision::Deny {
            reason: "INVALID_RISK_CONFIG",
        };
    }
    if sig.instrument.trim().is_empty() {
        return RiskDecision::Deny {
            reason: "INVALID_INSTRUMENT",
        };
    }
    if sig.proposed_risk_bps == 0 {
        return RiskDecision::Deny {
            reason: "ZERO_RISK_PROPOSAL",
        };
    }
    if st.equity_fixed <= 0 || st.equity_peak_fixed <= 0 || st.equity_fixed > st.equity_peak_fixed {
        return RiskDecision::Deny {
            reason: "INVALID_EQUITY_STATE",
        };
    }

    // --- kill switches first (fail closed) ---
    if !st.reconciled {
        return RiskDecision::Deny {
            reason: "RECONCILIATION_MISMATCH",
        };
    }
    if st.last_tick_ms > now_ms {
        return RiskDecision::Deny {
            reason: "MARKET_DATA_FROM_FUTURE",
        };
    }
    if now_ms - st.last_tick_ms > cfg.max_tick_age_ms {
        return RiskDecision::Deny {
            reason: "STALE_MARKET_DATA",
        };
    }
    if !st.heartbeat_ok {
        // A caller-supplied flag cannot prove that an order truly reduces an open position.
        return RiskDecision::Deny {
            reason: "HEARTBEAT_LOSS",
        };
    }
    // --- drawdown HARD STOP ---
    // drawdown_bps = (peak - equity) / peak * 10000
    let peak = i128::from(st.equity_peak_fixed);
    let equity = i128::from(st.equity_fixed);
    let drawdown_bps = (peak - equity) * 10_000 / peak;
    if drawdown_bps >= i128::from(cfg.max_drawdown_bps) {
        return RiskDecision::Deny {
            reason: "MAX_DRAWDOWN_HARD_STOP",
        };
    }
    // --- pause after consecutive losses ---
    if st.paused_until_ms > now_ms {
        return RiskDecision::Deny {
            reason: "PAUSED_CONSECUTIVE_LOSSES",
        };
    }
    if st.consecutive_losses >= cfg.max_consecutive_losses {
        return RiskDecision::Deny {
            reason: "CONSECUTIVE_LOSS_LIMIT",
        };
    }
    // --- daily trade count ---
    if st.trades_today >= cfg.max_trades_per_day {
        return RiskDecision::Deny {
            reason: "MAX_TRADES_PER_DAY",
        };
    }
    // --- per-trade risk cap (LLM conviction_score is NOT consulted) ---
    if sig.proposed_risk_bps > cfg.max_risk_per_trade_bps {
        return RiskDecision::Deny {
            reason: "RISK_PER_TRADE_EXCEEDED",
        };
    }
    // reduce-only requested -> honor it
    if sig.reduce_only {
        return RiskDecision::ReduceOnlyProposal {
            reason: "REQUESTED_REDUCE_ONLY",
        };
    }
    RiskDecision::EligibleProposal {
        risk_bps: sig.proposed_risk_bps,
    }
}

/// Compute a proposed OrderIntent quantity from proposal risk. Deterministic, no float.
/// The result is not authorized for submission.
pub fn position_size_fixed(
    equity_fixed: i64,
    risk_bps: u32,
    stop_distance_fixed: i64,
) -> Result<i64, PositionSizeError> {
    if equity_fixed <= 0 {
        return Err(PositionSizeError::NonPositiveEquity);
    }
    if risk_bps == 0 {
        return Err(PositionSizeError::ZeroRisk);
    }
    if risk_bps > 10_000 {
        return Err(PositionSizeError::RiskBpsOutOfRange);
    }
    if stop_distance_fixed <= 0 {
        return Err(PositionSizeError::NonPositiveStopDistance);
    }

    let numerator = i128::from(equity_fixed)
        .checked_mul(i128::from(risk_bps))
        .and_then(|value| value.checked_mul(i128::from(SCALE)))
        .ok_or(PositionSizeError::QuantityOutOfRange)?;
    let denominator = i128::from(stop_distance_fixed)
        .checked_mul(10_000)
        .ok_or(PositionSizeError::QuantityOutOfRange)?;
    let quantity = numerator / denominator;
    if quantity <= 0 {
        return Err(PositionSizeError::QuantityOutOfRange);
    }
    i64::try_from(quantity).map_err(|_| PositionSizeError::QuantityOutOfRange)
}
