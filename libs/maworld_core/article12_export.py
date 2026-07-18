"""EU AI Act Article-12 export — from our OWN PFI signals (×4 'advantage', 0.88-0.9): 'Article 12 is,
almost verbatim, a bi-temporal audit-trail-and-memory requirement'. Turns MAWorld's ledger/evidence/gate
records into an append-only, hash-chained, bi-temporal compliance record (the product wedge PFI keeps
naming). Each record: WHO (NHI caller) did WHAT, WHEN (event+record time = bi-temporal), under which
PERMISSIONS, the DECISION, RISK, human OVERSIGHT, and PROOF."""
from __future__ import annotations
import hashlib, json, time
from dataclasses import dataclass, field

REQUIRED = ["agent_id", "action", "event_time", "decision", "capability_ref", "risk_level"]

@dataclass
class Article12Record:
    agent_id: str                     # NHI / caller identity
    action: str
    event_time: float                 # when the action happened (valid time)
    decision: str                     # ALLOW | DENY | REQUIRE_CONFIRMATION
    capability_ref: str               # which permission authorized it
    risk_level: str
    evidence_ref: str = ""            # proof pointer (Evidence acceptance / ledger hash)
    human_oversight: str = ""         # confirmation token id, if high-impact
    outcome: str = ""
    record_time: float = field(default_factory=time.time)   # when logged (transaction time)

class ComplianceLog:
    """Append-only, hash-chained (tamper-evident) bi-temporal Article-12 log."""
    def __init__(self): self._chain = []
    def append(self, rec: Article12Record):
        missing = [k for k in REQUIRED if not getattr(rec, k, None)]
        if missing:
            raise ValueError(f"Article-12 record missing required fields: {missing}")
        prev = self._chain[-1]["hash"] if self._chain else "GENESIS"
        body = json.dumps(rec.__dict__, sort_keys=True)
        h = hashlib.sha256((prev + body).encode()).hexdigest()
        self._chain.append({"prev": prev, "record": rec.__dict__, "hash": h})
        return h
    def verify(self) -> bool:
        prev = "GENESIS"
        for e in self._chain:
            if e["prev"] != prev: return False
            body = json.dumps(e["record"], sort_keys=True)
            if hashlib.sha256((prev + body).encode()).hexdigest() != e["hash"]: return False
            prev = e["hash"]
        return True
    def export(self) -> dict:
        return {"standard": "EU AI Act Article 12 (bi-temporal audit trail)", "count": len(self._chain),
                "tamper_evident": self.verify(), "records": self._chain}

# EU AI Act Art.12(2) logging purposes + retention (research: tamper-evident, >=6mo / 24mo biometric)
LOG_PURPOSES = {"risk_situation":"Art.79(1) risk / substantial modification",
                "post_market":"Art.72 post-market monitoring", "operation":"Art.26(5) operation monitoring"}
def retention_days(biometric_or_le=False) -> int:
    return 730 if biometric_or_le else 183   # 24 months vs 6 months minimum
def classify_purpose(rec) -> str:
    d=(rec.decision or "").upper()
    if d in ("DENY","REQUIRE_CONFIRMATION") or rec.risk_level in ("high","critical"): return "risk_situation"
    return "operation"

class ComplianceViolationError(Exception): pass
# Agent-governance field checklist (Gemini DR: fields-by-field for Conformity Assessment)
ART12_FIELDS = ["event_uuid","timestamp_utc","nhi_identity_uri","intent_hash","retrieval_provenance",
                "action_verdict","human_override_flag","risk_trigger_event","prev_hash"]
def validate_retention(deployer_retention_days: int, provider_retention_days: int):
    """Art.26(6): deployer must keep logs 'at least six months' (183d). Auto-deletion before that is
    a direct legal violation (fines up to EUR 35M / 7% turnover)."""
    if deployer_retention_days < 183:
        raise ComplianceViolationError(
            f"Article 26(6) violation: deployer_retention_days={deployer_retention_days} < 'at least six months' (183)")
    if provider_retention_days < 183:
        raise ComplianceViolationError("Article 26(6) violation: provider_retention below 183 days")
    return True
