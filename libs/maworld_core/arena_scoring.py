"""Arena scoring — a statistically honest leaderboard. Rewritten after the DR round refuted v1.

Refutations accepted (both reproduced on our own code):
  F) Bradley-Terry over RAW mean-PnL is not a valid ranking: one lucky outlier at n=1 outranks a
     steady agent at n=100. Our own v1 test PASSED while demonstrating exactly this bug — the
     "1 winning trade beats 5 losing trades" assertion was celebrating the flaw.
  H) LLM traders show extreme run-to-run variance (AlphaForgeBench 2026) even under deterministic
     decoding. One tournament is weak evidence. Paired-comparison power (alpha=.05, power=.8):
     ~32 episodes for a 0.5σ effect, ~87 for 0.3σ, ~196 for 0.2σ — before any correction for serial
     correlation, fat tails, or multiplicity across ten agents.

Therefore: the unit of comparison is an EPISODE under a common ex-ante risk budget and cost model;
every rank carries uncertainty; and no winner is declared below the pre-registered minimum.
"""
from __future__ import annotations
import math, random

MIN_EPISODES_PROVISIONAL = 30      # below this, do not rank at all
MIN_EPISODES_PUBLISH     = 100     # below this, never declare a "winner"

class InsufficientEpisodes(RuntimeError): pass

def required_episodes(effect_size: float) -> int:
    """Paired comparison, alpha=0.05 two-sided, power=0.80: n ≈ (z_{1-a/2} + z_{1-b})^2 / d^2.
    Gives ~32 / ~87 / ~196 for d = 0.5 / 0.3 / 0.2 — the numbers the audit quoted."""
    if effect_size <= 0: raise ValueError("effect_size must be > 0")
    return math.ceil((1.959964 + 0.841621) ** 2 / (effect_size ** 2))

def bootstrap_ci(xs, iters: int = 2000, alpha: float = 0.05, seed: int = 7):
    """Percentile bootstrap CI for the mean. No normality assumption — PnL has fat tails."""
    xs = list(xs)
    if not xs: return (0.0, 0.0)
    if len(xs) == 1: return (xs[0], xs[0])
    rnd = random.Random(seed); n = len(xs)
    means = sorted(sum(rnd.choice(xs) for _ in range(n)) / n for _ in range(iters))
    lo = means[int((alpha / 2) * iters)]; hi = means[min(iters - 1, int((1 - alpha / 2) * iters))]
    return (round(lo, 6), round(hi, 6))

def shrunk_mean(xs, grand_mean: float, prior_n: float = 10.0) -> float:
    """Empirical-Bayes style shrinkage toward the grand mean: a single lucky episode gets pulled back,
    so small-n luck cannot masquerade as latent strength."""
    xs = list(xs)
    if not xs: return grand_mean
    n = len(xs); m = sum(xs) / n
    return (n * m + prior_n * grand_mean) / (n + prior_n)

def paired_bt(episodes: dict) -> dict:
    """Bradley-Terry on PAIRED per-episode differences d_e = U_i,e - U_j,e, using only episodes where
    both agents were active. This is what 'pairwise BT' actually requires — not a comparison of two
    unrelated averages taken over different track lengths."""
    ids = list(episodes)
    wins = {i: 0.0 for i in ids}; games = {i: 0.0 for i in ids}
    for a in range(len(ids)):
        for b in range(a + 1, len(ids)):
            i, j = ids[a], ids[b]
            common = min(len(episodes[i]), len(episodes[j]))     # aligned episodes only
            if common == 0: continue
            wi = sum(1 for e in range(common) if episodes[i][e] > episodes[j][e])
            wj = sum(1 for e in range(common) if episodes[j][e] > episodes[i][e])
            ties = common - wi - wj
            wins[i] += wi + 0.5 * ties; wins[j] += wj + 0.5 * ties
            games[i] += common; games[j] += common
    return {i: (round(wins[i] / games[i], 4) if games[i] else None) for i in ids}

def leaderboard(episodes: dict, min_publish: int = MIN_EPISODES_PUBLISH,
                min_rank: int = MIN_EPISODES_PROVISIONAL) -> dict:
    """episodes: agent_id -> list of EPISODE utilities (after costs, under a common risk budget).

    Returns rows with uncertainty and a winner ONLY if the evidence supports one:
      * every agent must clear `min_rank` to be ranked at all;
      * a winner requires `min_publish` episodes AND a bootstrap CI that does not overlap the
        runner-up's CI. Otherwise: no winner, and we say why.
    """
    if not episodes: raise InsufficientEpisodes("no episodes")
    all_vals = [v for xs in episodes.values() for v in xs]
    grand = sum(all_vals) / len(all_vals) if all_vals else 0.0
    bt = paired_bt(episodes)
    rows = []
    for aid, xs in episodes.items():
        n = len(xs)
        lo, hi = bootstrap_ci(xs)
        rows.append({"agent_id": aid, "episodes": n,
                     "mean": round(sum(xs) / n, 6) if n else 0.0,
                     "shrunk_mean": round(shrunk_mean(xs, grand), 6),
                     "ci95": (lo, hi), "bt_score": bt.get(aid),
                     "status": "RANKED" if n >= min_rank else "UNRANKED_INSUFFICIENT_N"})
    ranked = [r for r in rows if r["status"] == "RANKED"]
    ranked.sort(key=lambda r: -r["shrunk_mean"])          # shrunk, not raw: small-n luck is pulled in
    rows.sort(key=lambda r: (r["status"] != "RANKED", -r["shrunk_mean"]))

    winner, reason = None, ""
    if len(ranked) < 2:
        reason = (f"no winner: fewer than 2 agents cleared {min_rank} episodes "
                  f"(run-to-run variance makes a short track meaningless)")
    else:
        top, second = ranked[0], ranked[1]
        if top["episodes"] < min_publish:
            reason = (f"no winner: leader has {top['episodes']} episodes < {min_publish} required to "
                      f"publish a winner (need ~{required_episodes(0.3)} for a 0.3σ effect)")
        elif top["ci95"][0] <= second["ci95"][1]:
            reason = ("no winner: leader's 95% CI overlaps the runner-up's — the difference is not "
                      "statistically distinguishable from luck")
        else:
            winner = top["agent_id"]
            reason = "winner: CI separated from the runner-up over a sufficient track"
    return {"rows": rows, "winner": winner, "publishable": winner is not None, "reason": reason,
            "min_rank": min_rank, "min_publish": min_publish}
