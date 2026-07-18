"""Proves every ACTIVE security module resolves to libs/maworld_core (one implementation) and catalogs
frozen spike copies as historical evidence (intentionally not rewired)."""
import importlib.util, os, sys
from pathlib import Path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
# (active shim path, module name, a symbol that must originate in maworld_core)
ACTIVE = [
 ("services/evidence-engine/evidence_engine.py","evidence_engine","verify","evidence_engine"),
 ("services/workflow-runtime/hardened_effect_registry.py","hardened_effect_registry","HardenedEffectRegistry","hardened_effect_registry"),
 ("services/workflow-runtime/external_effect_registry.py","external_effect_registry","ExternalEffectRegistry","hardened_effect_registry"),
 ("services/action-authority/action_authority.py","action_authority","execute","action_authority"),
 ("services/mcp-auth/mcp_token_validator.py","mcp_token_validator","validate","mcp_token_validator"),
 ("apps/trading-cell/venue-adapters/trading_safety.py","trading_safety","safe_submit","trading_safety"),
 ("services/canon-promoter/canon_sod.py","canon_sod","CanonPromoter","canon_sod"),
 ("services/secrets-broker/secrets_broker.py","secrets_broker","SecretsBroker","secrets_broker"),
 ("apps/money-forge/money_forge_v2.py","money_forge_v2","MoneyForgeGate","money_forge_v2"),
 ("services/eval-registry/eval_registry.py","eval_registry","EvalRegistry","eval_registry"),
]
P=F=0
def ok(n,c,d=""):
    global P,F; b=bool(c); P+=b; F+=(not b); print(("  PASS " if b else "  FAIL ")+n+("" if b else f" <- {d}"))
for rel,mod,sym,canonical in ACTIVE:
    spec=importlib.util.spec_from_file_location(mod, os.path.join(ROOT,rel))
    m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    origin=getattr(getattr(m,sym),"__module__","?")
    ok(f"{mod}: '{sym}' originates in maworld_core (single source)", origin=="maworld_core."+canonical, f"got {origin}")
# catalog frozen spike copies (historical evidence, NOT active)
spikes=Path(ROOT)/"spikes"
dups=sum(1 for pattern in ("*/effect_registry.py","*/gate_bridge.py") for _ in spikes.glob(pattern))
print(f"\nfrozen spike security copies (historical evidence, not active): {dups}")
print(f"TALLY single-source: PASS={P} FAIL={F}")
sys.exit(1 if F else 0)
