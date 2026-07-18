"""CryptoGuides bridge — connect the owner's own knowledge base (cryptoguidessite.vercel.app, 113
guides + /api/guides) to MAWorld through the UNTRUSTED-input pipeline. Same pattern as pfi_bridge:
reuse, never duplicate; the site is a SOURCE, never an authority.

Why untrusted even though it is the owner's own site: it is a public web property with a JSON API.
Anything fetched over the wire can be tampered with, cached, or poisoned, and a guide is prose — the
perfect carrier for an injected instruction. So every guide crosses input_guard and lands as PROPOSED
memory with provenance, never as canon.

Invariants:
  * Guide != verified fact. Guides land as PROPOSED (Governed Memory), never canon.
  * A guide's "do X" is a gated PROPOSAL (authoritative=False), never auto-applied.
  * Provenance (url, slug, fetched_at) preserved; injected instructions quarantined.

The catalog is also a CROSSWALK: the owner's guides map onto MAWorld modules almost one-to-one, which
makes the gap analysis run in both directions — guides with no module (unbuilt ideas) and modules with
no guide (undocumented behaviour).
"""
from __future__ import annotations
import time
from maworld_core.input_guard import admit_input, scan
from maworld_core.memory_provenance import make_item, verify_item

SITE = "https://cryptoguidessite.vercel.app"
API = SITE + "/api/guides"
GUIDES_TRUST = 0.5      # 'tool'-grade: owner's knowledge base, but web-delivered -> cannot carry canon

# guide slug -> MAWorld module it maps onto (built from the live catalog, 113 slugs)
CROSSWALK = {
    # governance / authority
    "adaptive-delegation-gate":            "action_authority",
    "state-authority-plane-evolution":     "action_authority",
    "capability-passports-sap":            "capability + sap_bridge",
    "d3-tool-io-bridge-contract":          "action_authority (ContinuityOS D3 preflight)",
    "bybit-uta-defensive-veto":            "policy_engine (deny-override)",
    "regime-gate-scorecard":               "policy_engine",
    # trust / reliability  (== our wedge)
    "ai-agent-trust-layer-reliability":    "compliance_boundary  <-- WEDGE",
    "ai-agent-reliability-audit":          "error_budget + evidence_engine",
    "decision-trace-audit":                "trace_bridge + article12_export",
    "agent-self-healing":                  "improvement_engine",
    "anti-looping-monitor":                "error_budget (circuit-break)",
    "fleet-coordinator-drift-monitoring":  "agent_registry + error_budget",
    "execution-drift-daemon":              "hardened_effect_registry (reconcile)",
    "pnl-protection-daemons":              "trading_safety + agent_containment",
    # anti-self  (our core invariant)
    "anti-self-attention-trading-psychology": "evidence_engine (agent cannot accept own work)",
    "tilt-index-antiself":                 "evidence_engine + error_budget",
    # safety / sandbox / secrets
    "multi-agent-system-safety":           "agent_containment",
    "mas-managed-coevolution-sandbox-isolation": "tier2_runner + sandbox_limits",
    "security-sandboxing":                 "sandbox_limits",
    "reviewer-sandbox-split":              "key_custody (separation-of-duties)",
    "tee-agent-secrets":                   "secrets_broker + remote_attestation",
    "omnicore-loop-self-preservation":     "agent_containment (global-kill)",
    # memory
    "best-longterm-memory-systems-for-ai": "bitemporal_memory",
    "mirrorcore-compactdigest-memory-compression": "memory_provenance",
    "mirrorcore-compression":              "memory_provenance",
    "mirrorcore-seeding-identity-persistence": "sovereign_memir_bridge",
    "vector-graph-hybrid-search":          "bitemporal_memory",
    "instructed-retriever":                "input_guard (untrusted retrieval)",
    "context-garbage-collection":          "bitemporal_memory (supersede)",
    "prompt-compression-entropy":          "budget_router",
    "lsh-deduplication":                   "memory_provenance",
    # multi-agent / dialectic
    "mixture-of-agents-consensus":         "gpts_moa_bridge",
    "multi-model-debate":                  "gpts_moa_bridge (challenger)",
    "multigpt-bridge-federated-ai-arbitration": "gpts_moa_bridge",
    "archiveos-multigpt-bridge-integration":"gpts_moa_bridge",
    "multiagent-orchestration-autonomous-research": "agents_runner",
    "active-inference-agents":             "agents_runner",
    "sovereign-agent-core":                "agent_registry",
    "reflex-layer-ooda-monitoring":        "reflex_bridge",
    "fractal-intelligence-scouts-scribes-attention": "global_cycle (fractal invariant)",
    "frontier-models-cost-routing":        "budget_router",
    # market microstructure  (== arena_frictions)
    "avellaneda-stoikov-inventory":        "arena_frictions (inventory/market-making)",
    "transient-price-impact-decay":        "arena_frictions (Almgren-Chriss)",
    "avx512-hawkes-engine":                "arena_frictions (SCFT microstructure)",
    "vpin-flow-toxicity":                  "arena_frictions",
    "obi-order-book-imbalance":            "arena_frictions",
    "lob-queue-position":                  "arena_frictions",
    "queue-admission-simulator":           "arena_frictions",
    "queue-calibration-model":             "arena_frictions (gamma/eta calibration) <-- OPEN GAP",
    "depth-liquidity-policy":              "arena_frictions",
    "order-lifetime-cancellation":         "arena_frictions",
    "crypto-microstructure-2026":          "arena_frictions",
    # statistics / validation  (== arena_scoring)
    "how-to-validate-edge-oos-bootstrap":  "arena_scoring (bootstrap CI, OOS)  <-- CONFIRMS DR FIX",
    "walkforward-ensemble":                "arena_scoring",
    "survival-math-ergodicity-kelly":      "trading_safety (sizing)",
    "volatility-sizing-policy":            "trading_safety",
    "why-90-percent-strategies-lose":      "arena_scoring (small-n luck)",
    "diversification-illusion-bots":       "arena_scoring",
    "pochemu-strategii-teryayut-dengi":    "arena_scoring",
    # money
    "monetization-matrix-4x3":             "money_forge_v2 + pilot_gate",
}

def parse_catalog(slugs) -> list:
    """Turn the site catalog into governed items. Slugs are data, never instructions."""
    out = []
    for s in slugs:
        s = (s or "").strip()
        if not s: continue
        out.append({"slug": s, "url": f"{SITE}/guides/{s}",
                    "module": CROSSWALK.get(s), "mapped": s in CROSSWALK})
    return out

def _ingest_guide_with_bound_key(slug: str, body: str, mem_key: bytes) -> dict:
    """One guide -> PROPOSED memory with provenance, or QUARANTINED if it carries instructions.
    A guide that says 'ignore previous instructions' or 'run this command' is exactly the attack the
    owner's own 'instructed-retriever' guide warns about — so it never reaches memory as fact."""
    url = f"https://cryptoguidessite.vercel.app/guides/{slug}"
    verdict = admit_input(body or "", source="external")
    if not verdict["admit"]:
        return {"status": "QUARANTINED", "slug": slug, "url": url,
                "reason": "input_guard: prompt-injection in guide body",
                "signals": scan(body or "")}
    item = make_item(mem_key, (body or "")[:4000], url, 0.5)
    return {"status": "PROPOSED", "slug": slug, "url": url, "trust": 0.5,
            "module": CROSSWALK.get(slug), "item": item,
            "fetched_at": time.time(),
            "authoritative": False,
            "note": "guide is a source, not canon; any 'do X' becomes a gated proposal"}


MIN_PROVENANCE_KEY_BYTES = 16


class GuideMemoryIngestor:
    """Proposal-only ingestor with construction-time provenance config.

    The trusted composition root supplies the key once. Individual guide calls
    cannot select a key, trust score, timestamp, source class, or authority
    flag. The HMAC proves record integrity only and never promotes web prose.
    """

    __slots__ = ("__mem_key",)

    def __init__(self, *, mem_key: bytes):
        if (
            not isinstance(mem_key, bytes)
            or len(mem_key) < MIN_PROVENANCE_KEY_BYTES
        ):
            raise ValueError(
                f"explicit provenance key of at least {MIN_PROVENANCE_KEY_BYTES} bytes is required"
            )
        self.__mem_key = bytes(mem_key)

    def ingest_guide(self, slug: str, body: str) -> dict:
        if not isinstance(slug, str) or not slug.strip():
            raise ValueError("slug must be a non-empty string")
        return _ingest_guide_with_bound_key(slug.strip(), body, self.__mem_key)


def ingest_guide(*args, **kwargs):
    """Fail-closed tombstone for the old per-call/default-key API."""
    raise TypeError(
        "per-call guide ingestion is disabled; construct GuideMemoryIngestor "
        "with trusted provenance configuration"
    )

def crosswalk_report(slugs) -> dict:
    """Two-directional gap analysis: guides without a module (unbuilt), modules without a guide."""
    cat = parse_catalog(slugs)
    mapped = [c for c in cat if c["mapped"]]
    unmapped = [c["slug"] for c in cat if not c["mapped"]]
    modules = sorted({c["module"].split(" ")[0] for c in mapped})
    return {"guides_total": len(cat), "guides_mapped": len(mapped), "guides_unmapped": len(unmapped),
            "modules_covered": len(modules), "modules": modules,
            "unmapped_sample": unmapped[:12],
            "coverage_pct": round(100.0 * len(mapped) / max(1, len(cat)), 1)}
