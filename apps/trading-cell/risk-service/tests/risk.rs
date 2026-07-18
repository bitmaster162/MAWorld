use trading_risk::*;

fn base_state() -> RiskState {
    RiskState {
        equity_fixed: 100 * SCALE,
        equity_peak_fixed: 100 * SCALE,
        trades_today: 0,
        consecutive_losses: 0,
        paused_until_ms: 0,
        last_tick_ms: 1000,
        reconciled: true,
        heartbeat_ok: true,
    }
}
fn sig(risk_bps: u32) -> SignalProposal {
    SignalProposal {
        instrument: "BTC-PERP".into(),
        side: Side::Buy,
        conviction_score: 99,
        proposed_risk_bps: risk_bps,
        reduce_only: false,
    }
}

#[test]
fn marks_within_limits_as_eligible_proposal() {
    let d = evaluate_proposal(&sig(50), &RiskConfig::default(), &base_state(), 1050);
    assert_eq!(d, RiskDecision::EligibleProposal { risk_bps: 50 });
}
#[test]
fn conviction_score_ignored_when_risk_exceeds() {
    // conviction 99 must NOT let a 2% risk through (cap is 1% = 100bps)
    let d = evaluate_proposal(&sig(200), &RiskConfig::default(), &base_state(), 1050);
    assert_eq!(
        d,
        RiskDecision::Deny {
            reason: "RISK_PER_TRADE_EXCEEDED"
        }
    );
}
#[test]
fn drawdown_hard_stop() {
    let mut st = base_state();
    st.equity_fixed = 89 * SCALE; // -11% from 100 peak
    assert_eq!(
        evaluate_proposal(&sig(50), &RiskConfig::default(), &st, 1050),
        RiskDecision::Deny {
            reason: "MAX_DRAWDOWN_HARD_STOP"
        }
    );
}
#[test]
fn stale_data_kill_switch() {
    let st = base_state(); // last_tick 1000
    assert_eq!(
        evaluate_proposal(&sig(50), &RiskConfig::default(), &st, 1000 + 101),
        RiskDecision::Deny {
            reason: "STALE_MARKET_DATA"
        }
    );
}
#[test]
fn reconciliation_mismatch_blocks() {
    let mut st = base_state();
    st.reconciled = false;
    assert_eq!(
        evaluate_proposal(&sig(50), &RiskConfig::default(), &st, 1050),
        RiskDecision::Deny {
            reason: "RECONCILIATION_MISMATCH"
        }
    );
}
#[test]
fn heartbeat_loss_denies_unverified_reduce_only_claim() {
    let mut st = base_state();
    st.heartbeat_ok = false;
    let mut s = sig(50);
    s.reduce_only = true;
    assert_eq!(
        evaluate_proposal(&s, &RiskConfig::default(), &st, 1050),
        RiskDecision::Deny {
            reason: "HEARTBEAT_LOSS"
        }
    );
    assert_eq!(
        evaluate_proposal(&sig(50), &RiskConfig::default(), &st, 1050),
        RiskDecision::Deny {
            reason: "HEARTBEAT_LOSS"
        }
    );
}
#[test]
fn max_trades_per_day() {
    let mut st = base_state();
    st.trades_today = 20;
    assert_eq!(
        evaluate_proposal(&sig(50), &RiskConfig::default(), &st, 1050),
        RiskDecision::Deny {
            reason: "MAX_TRADES_PER_DAY"
        }
    );
}
#[test]
fn consecutive_losses_block() {
    let mut st = base_state();
    st.consecutive_losses = 3;
    assert_eq!(
        evaluate_proposal(&sig(50), &RiskConfig::default(), &st, 1050),
        RiskDecision::Deny {
            reason: "CONSECUTIVE_LOSS_LIMIT"
        }
    );
}
#[test]
fn position_size_is_fixed_point() {
    // equity 100, risk 100bps (1%) => risk amount 1.0; stop distance 0.5 => size 2.0
    let sz = position_size_fixed(100 * SCALE, 100, SCALE / 2).unwrap();
    assert_eq!(sz, 2 * SCALE);
}

#[test]
fn drawdown_math_cannot_overflow_or_wrap() {
    let mut st = base_state();
    st.equity_peak_fixed = i64::MAX;
    st.equity_fixed = i64::MIN;
    assert_eq!(
        evaluate_proposal(&sig(50), &RiskConfig::default(), &st, 1050),
        RiskDecision::Deny {
            reason: "INVALID_EQUITY_STATE"
        }
    );

    st.equity_fixed = 1;
    assert_eq!(
        evaluate_proposal(&sig(50), &RiskConfig::default(), &st, 1050),
        RiskDecision::Deny {
            reason: "MAX_DRAWDOWN_HARD_STOP"
        }
    );

    // This made the old `dd as u32` calculation wrap to zero exactly.
    st.equity_peak_fixed = 1;
    st.equity_fixed = -268_435_455;
    assert_eq!(
        evaluate_proposal(&sig(50), &RiskConfig::default(), &st, 1050),
        RiskDecision::Deny {
            reason: "INVALID_EQUITY_STATE"
        }
    );
}

#[test]
fn invalid_equity_and_future_market_data_fail_closed() {
    for equity in [0, -1] {
        let mut st = base_state();
        st.equity_fixed = equity;
        assert_eq!(
            evaluate_proposal(&sig(50), &RiskConfig::default(), &st, 1050),
            RiskDecision::Deny {
                reason: "INVALID_EQUITY_STATE"
            }
        );
    }

    let mut st = base_state();
    st.last_tick_ms = 1051;
    assert_eq!(
        evaluate_proposal(&sig(50), &RiskConfig::default(), &st, 1050),
        RiskDecision::Deny {
            reason: "MARKET_DATA_FROM_FUTURE"
        }
    );
}

#[test]
fn malformed_config_and_proposal_fail_closed() {
    let cfg = RiskConfig {
        max_drawdown_bps: 10_001,
        ..RiskConfig::default()
    };
    assert_eq!(
        evaluate_proposal(&sig(50), &cfg, &base_state(), 1050),
        RiskDecision::Deny {
            reason: "INVALID_RISK_CONFIG"
        }
    );

    assert_eq!(
        evaluate_proposal(&sig(0), &RiskConfig::default(), &base_state(), 1050),
        RiskDecision::Deny {
            reason: "ZERO_RISK_PROPOSAL"
        }
    );

    let mut empty = sig(50);
    empty.instrument = "   ".into();
    assert_eq!(
        evaluate_proposal(&empty, &RiskConfig::default(), &base_state(), 1050),
        RiskDecision::Deny {
            reason: "INVALID_INSTRUMENT"
        }
    );
}

#[test]
fn position_size_rejects_invalid_and_unrepresentable_inputs() {
    assert_eq!(
        position_size_fixed(-SCALE, 100, SCALE),
        Err(PositionSizeError::NonPositiveEquity)
    );
    assert_eq!(
        position_size_fixed(SCALE, 0, SCALE),
        Err(PositionSizeError::ZeroRisk)
    );
    assert_eq!(
        position_size_fixed(SCALE, 10_001, SCALE),
        Err(PositionSizeError::RiskBpsOutOfRange)
    );
    assert_eq!(
        position_size_fixed(SCALE, 100, 0),
        Err(PositionSizeError::NonPositiveStopDistance)
    );
    assert_eq!(
        position_size_fixed(i64::MAX, 10_000, 1),
        Err(PositionSizeError::QuantityOutOfRange)
    );
}
