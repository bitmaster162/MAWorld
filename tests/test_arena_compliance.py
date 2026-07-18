import sys, os
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT,"libs"))
from maworld_core.arena_compliance import (assert_no_autonomy_claim, AIWashingRisk, assert_impersonal,
    PublisherExclusionLost, disclaimer_is_sufficient, gate_rationale, validate_retention,
    RetentionViolation, assert_closed_loop_points, GamblingRisk, art50_publish,
    TransparencyViolation, RTS6_MIN_DAYS, AI_ACT_MIN_DAYS, compliance_report)
P=F=0
def ok(n,c,d=""):
    global P,F; b=bool(c); P+=b; F+=(not b); print(("  PASS " if b else "  FAIL ")+n+("" if b else f" <- {d}"))

# ---- AI-washing (Presto Automation Jan-2025; Delphia/Global Predictions Mar-2024) ----
for claim in ["Fully autonomous AI agents trade for you", "our AI trades itself, no human involvement",
              "полностью автономные агенты", "AI that trades by itself"]:
    try: assert_no_autonomy_claim(claim, governance_disclosed=True); ok(f"autonomy claim rejected: {claim[:28]}", False, "accepted")
    except AIWashingRisk: ok(f"AI-washing blocked: '{claim[:28]}...'", True)
try: assert_no_autonomy_claim("Governed AI proposers compete on a paper arena.", governance_disclosed=False)
except AIWashingRisk as e: ok("governance MUST be disclosed wherever capability is described", "must be disclosed" in str(e))
ok("honest copy passes: governed proposers + disclosure",
   assert_no_autonomy_claim("Governed AI proposers compete on a paper arena; every trade passes a "
                            "deterministic risk gate with a kill-switch.", governance_disclosed=True))

# ---- Publisher's Exclusion (Lowe / Tokyo Joe / Weiss) — our OWN planned features ----
for feat in ["leaderboard_filter_by_viewer_assets","favourite_model_alerts","paid_consensus_signal",
             "portfolio_sized_recommendation","volatility_triggered_signals","broker_account_link"]:
    try: assert_impersonal(feat); ok(f"{feat} rejected", False, "accepted!")
    except PublisherExclusionLost as e: ok(f"personalization blocked: {feat}", True)
ok("neutral ranking is allowed", assert_impersonal("global_neutral_leaderboard"))
ok("a disclaimer is encoded as NEVER sufficient (Global Predictions/ClearPath 2024)",
   disclaimer_is_sufficient() is False)

# ---- MAR Art.20: hallucinated rationale must not be disseminated as fact ----
g = gate_rationale("ASSET_7 is falling because the issuer just declared bankruptcy")
ok("MAR: unverified factual claim -> NOT publishable", not g["publishable"] and g["unverified_claims"])
ok("MAR: unsafe render redacts the invented fact", "[UNVERIFIED CLAIM REDACTED]" in g["safe_render"])
ok("MAR: pure opinion/technical rationale IS publishable",
   gate_rationale("ASSET_7 broke the 20-period high on rising volume; momentum favours long")["publishable"])
ok("MAR: a claim backed by the verified fact set is publishable",
   gate_rationale("issuer reported earnings", verified_facts={"reported"})["publishable"])

# ---- RTS 6 lex specialis: 183d was WRONG for algo trading ----
ok("AI Act floor alone is 183d", AI_ACT_MIN_DAYS == 183)
ok("RTS 6 demands ~5 years", RTS6_MIN_DAYS == 1825)
try: validate_retention(183, algo_trading_context=True); ok("183d rejected in algo context", False, "accepted!")
except RetentionViolation as e: ok("183d retention REFUSED once it is algo trading (RTS 6)", "RTS 6" in str(e))
ok("183d ok for a non-algo limited-risk system", validate_retention(183, algo_trading_context=False))
ok("5y passes the RTS 6 floor", validate_retention(1825, algo_trading_context=True))

# ---- prediction points: CFTC / Polymarket ----
try: assert_closed_loop_points(fiat_purchasable=True, cashable=False); ok("fiat-purchasable rejected", False, "accepted")
except GamblingRisk: ok("points purchasable with fiat -> refused (CFTC event contracts)", True)
try: assert_closed_loop_points(fiat_purchasable=False, cashable=True); ok("cashable rejected", False, "accepted")
except GamblingRisk: ok("points redeemable for money -> refused (Polymarket $1.4M)", True)
try: assert_closed_loop_points(False, False, tradeable_p2p=True); ok("p2p rejected", False, "accepted")
except GamblingRisk: ok("p2p-transferable points acquire market value -> refused", True)
ok("closed-loop points (no in, no out) are allowed", assert_closed_loop_points(False, False))

# ---- EU AI Act Art.50 (applies 2026-08-02) ----
for kw in ["ai_interaction_notice","machine_readable_watermark","public_interest_label"]:
    kwargs={"ai_interaction_notice":True,"machine_readable_watermark":True,"public_interest_label":True}
    kwargs[kw]=False
    try: art50_publish("reasoning log", **kwargs); ok(f"Art.50 missing {kw} rejected", False, "accepted")
    except TransparencyViolation: ok(f"Art.50: missing {kw} -> refused", True)
ok("Art.50 satisfied -> publish allowed", art50_publish("reasoning log", True, True, True))
ok("compliance_report states no autonomy is claimed", compliance_report()["autonomy_claimed"] is False)
ok("compliance_report keeps the residual risks visible", len(compliance_report()["residual"]) >= 2)

print(f"\nTALLY arena-compliance: PASS={P} FAIL={F}"); sys.exit(1 if F else 0)
