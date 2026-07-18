"""maworld_core — SINGLE SOURCE OF TRUTH for security-critical primitives.
Import from here everywhere. Active modules elsewhere are thin re-export shims so a fix here propagates
everywhere (fixes GPT DR-2 'duplicated security-critical modules; fix-once won't propagate').
Frozen spike copies (spikes/*) are immutable falsification evidence and are intentionally NOT rewired.
"""
CANONICAL = ["hardened_effect_registry","action_authority","evidence_engine",
             "mcp_token_validator","trading_safety","canon_sod"]
