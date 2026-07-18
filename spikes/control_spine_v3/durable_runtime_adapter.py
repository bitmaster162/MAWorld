"""DurableRuntimeAdapter (v1.4 §3.2) — the canonical resolution of the Temporal-vs-DBOS conflict.

The runtime is NOT frozen. Branch/effect/recovery contracts are runtime-independent; DBOS is the
FIRST reproducible spike (already proven in control_spine_v0: crash-recovery, no duplicate effect),
Temporal is a PRE-APPROVED FALLBACK / migration target. Selection is decided by the runtime gate
(v1.4 §3.3), not by report count.
"""
from __future__ import annotations
from abc import ABC, abstractmethod


class DurableRuntimeAdapter(ABC):
    """Contract every durable runtime candidate must satisfy for the control spine."""
    @abstractmethod
    def start_workflow(self, workflow_id: str, fn, *args): ...
    @abstractmethod
    def recover_pending(self) -> list: ...
    @abstractmethod
    def external_effect_once(self, idempotency_key: str, do_effect):
        """Fire an external side effect at most once per idempotency_key (ExternalEffectRegistry)."""


# --- runtime selection gate (v1.4 §3.3) ---
def select_runtime(evidence: dict) -> str:
    """Return 'DBOS' or 'TEMPORAL' per the canonical gate. DBOS wins when the reproducibility
    and simplicity conditions all hold; escalate to Temporal if any escalation trigger is true."""
    dbos_ok = all([
        evidence.get("recovery_test_passes"),
        evidence.get("no_duplicate_effect"),
        evidence.get("human_hold_resumes"),
        evidence.get("contracts_runtime_independent"),
        evidence.get("one_owner_ops_simple"),
        evidence.get("custom_glue_bounded"),
    ])
    escalate = any([
        evidence.get("dbos_evidence_unreproducible"),
        evidence.get("multi_language_workers_required"),
        evidence.get("signals_timers_dominate"),
        evidence.get("glue_exceeds_business_logic"),
        evidence.get("operator_reset_tooling_critical"),
        evidence.get("needs_distributed_cluster"),
    ])
    return "TEMPORAL" if (escalate or not dbos_ok) else "DBOS"


# Current canonical status: DBOS = FIRST SPIKE (control_spine_v0 evidence satisfies the gate);
# TEMPORAL = PRE-APPROVED FALLBACK. A DbosAdapter binds control_spine_v0's proven pattern; a
# TemporalAdapter implements the same ABC when an escalation trigger fires.
CURRENT = {
    "recovery_test_passes": True,        # control_spine_v0 RESULT.md
    "no_duplicate_effect": True,         # control_spine_v0 killtest
    "human_hold_resumes": True,          # gate HOLD path proven
    "contracts_runtime_independent": True,
    "one_owner_ops_simple": True,
    "custom_glue_bounded": True,
}
