"""Arena compliance guards — fail-closed code from an adversarial regulatory audit (Gemini DR round).

Every guard is one of OUR OWN planned features, refuted and turned into an executable constraint.
The audit's core finding: the features we sketched systematically destroy the legal defence we were
relying on. So the defence now lives in code, not in a doc paragraph.

  1. AI-WASHING. SEC: Delphia + Global Predictions (Mar 2024, $400k combined); Presto Automation
     (Jan 2025 — first non-adviser tech company fined). Claiming autonomous AI while hidden
     guardrails do the work = securities fraud (Rule 10b-5). Our governance is REAL and heavy —
     so it must be DISCLOSED, and "fully autonomous agents" must never be claimed.
  2. PUBLISHER'S EXCLUSION (Lowe v. SEC, 1985) is destroyed by personalization:
       leaderboard filtered by the viewer's assets (SEC v. Tokyo Joe, 2001: targeting = out),
       "your favourite model just shorted" alerts, paid consensus-signal subscriptions
       (Weiss Research, 2006: premium signals killed bona fide publisher status), and signals fired
       by volatility instead of a fixed schedule (breaks "general and regular circulation").
  3. DISCLAIMERS DO NOT SAVE US. Global Predictions / ClearPath Capital (2024): a hedge clause
     creating a false impression of waived fiduciary protection is ITSELF a §206 violation. ESMA
     finfluencer guidance: "not investment advice" has no force if the content objectively reads as
     a call to act or manufactures FOMO. A disclaimer is necessary, never sufficient.
  4. MAR Art.20 + Delegated Reg 2016/958: publishing a reasoning log that contains a HALLUCINATED
     fact is dissemination of false market information. Fact/opinion separation is mandatory —
     which is a hard problem precisely because LLMs hallucinate. So: gate the publication.
  5. RTS 6 (MiFID II) LEX SPECIALIS: algo-trading audit trails must be kept ~5 years, not the
     183 days that EU AI Act Art.12 alone implied.
  6. PREDICTION POINTS: CFTC enforcement (Polymarket: $1.4M + US geoblock). Points must be a closed
     loop — not fiat-purchasable, not cashable — or it is an unregulated event-contract market.
  7. EU AI ACT Art.50 (applies 2 Aug 2026): AI-interaction notice + machine-readable watermark on
     generated content + labelling AI text on matters of public interest (our reasoning inspector).
"""
from __future__ import annotations
import re

class AIWashingRisk(RuntimeError): pass
class PublisherExclusionLost(RuntimeError): pass
class MARViolation(RuntimeError): pass
class RetentionViolation(RuntimeError): pass
class GamblingRisk(RuntimeError): pass
class TransparencyViolation(RuntimeError): pass

# ---------------------------------------------------------------- 1. AI-washing
_AUTONOMY_CLAIMS = re.compile(
    r"fully autonomous|completely autonomous|no human (in|involvement|oversight)|"
    r"without human|human[- ]free|unsupervised ai|ai (that )?trades? (by )?itself|"
    r"полностью автоном|без участия человека|без человека|сам(о)? торгует", re.I)

def assert_no_autonomy_claim(marketing_text: str, governance_disclosed: bool) -> bool:
    """Presto Automation: overstating agent autonomy while guardrails do the work is fraud.
    We DO have hidden-from-nobody guardrails (gate, kill-switch, risk cap) — so we may never claim
    autonomy, and we must disclose the governance layer wherever we describe the agents."""
    if _AUTONOMY_CLAIMS.search(marketing_text or ""):
        raise AIWashingRisk(
            "autonomy claim + real guardrails = AI-washing (SEC v. Presto Automation, Jan 2025; "
            "Rule 10b-5). Describe agents as GOVERNED proposers, not autonomous traders.")
    if not governance_disclosed:
        raise AIWashingRisk("governance layer (gate, risk cap, kill-switch) must be disclosed "
                            "wherever agent capability is described")
    return True

# ---------------------------------------------------------------- 2. Publisher's Exclusion
PERSONALIZING_FEATURES = {
    "leaderboard_filter_by_viewer_assets": "SEC v. Tokyo Joe (2001): targeting individuals kills the exclusion",
    "favourite_model_alerts": "personalized 'your model just shorted' = individualized guidance",
    "paid_consensus_signal": "Weiss Research (2006): selling premium signals kills bona fide publisher status",
    "portfolio_sized_recommendation": "adapting to the viewer's deposit = personalized advice",
    "volatility_triggered_signals": "breaks 'general and regular circulation' (sporadic, market-reactive)",
    "broker_account_link": "MiFID II portfolio management + destroys Lowe outright",
}

def assert_impersonal(feature: str) -> bool:
    """Fail-closed on any feature that converts a publication into personalized advice."""
    if feature in PERSONALIZING_FEATURES:
        raise PublisherExclusionLost(f"{feature}: {PERSONALIZING_FEATURES[feature]}")
    return True

def disclaimer_is_sufficient() -> bool:
    """Encoded as a hard FALSE. Global Predictions / ClearPath (2024): a hedge clause implying a
    waiver of fiduciary protection is itself a §206 violation. ESMA: disclaimers do not cure content
    that reads as a call to act. A disclaimer is necessary and NEVER sufficient."""
    return False

# ---------------------------------------------------------------- 4. MAR: hallucinated rationale
_FACTUAL_CLAIM = re.compile(
    r"\b(bankrupt\w*|insolven\w*|default(ed|s)?|indict\w*|merger|acquisition|acquired|lawsuit|"
    r"sued|recall|earnings (beat|miss)|reported|announced|resigned|fired|hack(ed)?|breach|"
    r"банкрот\w*|дефолт\w*|иск|слияние|поглощение|отчитал\w*|объявил\w*)\b", re.I)

def gate_rationale(rationale: str, verified_facts: set | None = None) -> dict:
    """MAR requires facts to be clearly separated from opinions. An LLM justifying a short with an
    invented bankruptcy is false market information the moment we publish the reasoning inspector.
    So: any factual-sounding claim must be backed by the verified fact set, or it is quarantined and
    the rationale is NOT publishable as-is."""
    text = rationale or ""
    verified = {v.lower() for v in (verified_facts or set())}
    claims = [m.group(0) for m in _FACTUAL_CLAIM.finditer(text)]
    unverified = [c for c in claims if c.lower() not in verified]
    if unverified:
        return {"publishable": False, "unverified_claims": unverified,
                "reason": "MAR Art.20: unverified factual claim(s) in a published rationale — "
                          "quarantine or label as model opinion, do not disseminate as fact",
                "safe_render": re.sub(_FACTUAL_CLAIM, "[UNVERIFIED CLAIM REDACTED]", text)}
    return {"publishable": True, "unverified_claims": [], "reason": "opinion-only rationale"}

# ---------------------------------------------------------------- 5. Retention (RTS 6 lex specialis)
AI_ACT_MIN_DAYS = 183          # EU AI Act Art.26(6) deployer minimum
RTS6_MIN_DAYS = 5 * 365        # MiFID II RTS 6: algorithmic trading audit trail (~5 years)

def validate_retention(days: int, algo_trading_context: bool) -> bool:
    """AI Act Art.12/26(6) is NOT the binding floor once the activity is algorithmic trading:
    RTS 6 is lex specialis and demands years, not months. Selling consensus signals B2B plausibly
    drags us into that context — so the guard fails closed on the stricter rule."""
    floor = RTS6_MIN_DAYS if algo_trading_context else AI_ACT_MIN_DAYS
    if days < floor:
        raise RetentionViolation(
            f"retention {days}d < {floor}d required "
            f"({'MiFID II RTS 6 algo-trading audit trail' if algo_trading_context else 'EU AI Act Art.26(6)'})")
    return True

# ---------------------------------------------------------------- 6. Prediction points
def assert_closed_loop_points(fiat_purchasable: bool, cashable: bool, tradeable_p2p: bool = False) -> bool:
    """Polymarket ($1.4M CFTC penalty + US geoblock): the red line is monetization. Points survive
    only as a closed loop with no monetary value in or out."""
    if fiat_purchasable:
        raise GamblingRisk("points purchasable with fiat/crypto -> unregulated event-contract market (CFTC)")
    if cashable:
        raise GamblingRisk("points redeemable for money/assets -> gambling / unregistered derivatives")
    if tradeable_p2p:
        raise GamblingRisk("peer-to-peer transferable points acquire market value -> same exposure")
    return True

# ---------------------------------------------------------------- 7. EU AI Act Art.50 (from 2026-08-02)
def art50_publish(content: str, ai_interaction_notice: bool, machine_readable_watermark: bool,
                  public_interest_label: bool) -> bool:
    """Transparency obligations for limited-risk AI. Our reasoning inspector publishes AI-generated
    financial text = matter of public interest -> must be labelled and machine-readably marked."""
    if not ai_interaction_notice:
        raise TransparencyViolation("Art.50(1): users must be told they interact with an AI system")
    if not machine_readable_watermark:
        raise TransparencyViolation("Art.50(2): AI-generated content needs a machine-readable mark")
    if not public_interest_label:
        raise TransparencyViolation("Art.50(4): AI text on matters of public interest must be labelled")
    return True

def compliance_report() -> dict:
    """What an operator must be able to answer before the arena goes public."""
    return {
        "paper_only": True,
        "autonomy_claimed": False,
        "governance_disclosed": True,
        "personalization": "none (fail-closed guard)",
        "disclaimer_sufficient": disclaimer_is_sufficient(),
        "retention_days_required_if_algo_context": RTS6_MIN_DAYS,
        "points": "closed loop: not purchasable, not cashable",
        "art50_effective": "2026-08-02",
        "residual": ["operator omission needs a pre-registered schedule (see arena_ledger)",
                     "lookahead cannot be PROVEN absent — only minimized (live post-cutoff)"],
    }
