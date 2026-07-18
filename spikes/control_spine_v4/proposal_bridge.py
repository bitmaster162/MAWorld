"""Proposal Bridge (DR2 0x09) — the non-authoritative boundary between untrusted proposers
(brain/CTHA, LLM tool calls, subagent handoffs, provider SDK action objects) and the
authoritative control spine.

Input is UNTRUSTED. The Bridge: validates schema + provenance, rejects missing trace context,
STRIPS any supplied authority markers (execute/ALLOW/approval), resolves data class + target
adapter, mints a FRESH canonical ActionSpec (the proposal can never set authority), binds an
idempotency key, and submits. It NEVER executes and NEVER promotes canon.
"""
from __future__ import annotations
import hashlib, json, re, time, uuid
from dataclasses import dataclass, field

# keys a proposer might try to smuggle to fake authority -> always removed
AUTHORITY_MARKERS = {"decision", "execute", "allow", "approved", "approval", "may_execute",
                     "authority", "capability_token", "delegation_grant_id", "policy_decision_id"}
ALLOWED_ADAPTERS = {"filesystem"}                 # spike scope: temp-dir file writes only
ALLOWED_ROOT = "/work/out"                          # target must be under this root
SECRET_RE = re.compile(r"(sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{12,}|-----BEGIN|password\s*=)", re.I)


@dataclass
class ProposalValidationResult:
    ok: bool
    reason: str
    action_spec: dict | None = None
    stripped: list = field(default_factory=list)


def _has_trace(p): return bool(p.get("source_trace_id")) and bool(p.get("brain_run_id"))


def bridge(proposal: dict, seen_ids: set, now: float | None = None) -> ProposalValidationResult:
    now = time.time() if now is None else now
    # 1. schema
    if proposal.get("kind") != "ProposedActionSpec":
        return ProposalValidationResult(False, "REJECTED_SCHEMA")
    # 2/3. provenance + trace context
    if not _has_trace(proposal):
        return ProposalValidationResult(False, "REJECTED_MISSING_TRACE")
    # expired proposal
    if now > proposal.get("expires_at", now + 1):
        return ProposalValidationResult(False, "REJECTED_EXPIRED")
    # duplicate proposal (idempotency at the bridge)
    pid = proposal.get("proposal_id")
    if not pid or pid in seen_ids:
        return ProposalValidationResult(False, "REJECTED_DUPLICATE")
    # secret embedded in proposal -> quarantine
    if SECRET_RE.search(json.dumps(proposal)):
        return ProposalValidationResult(False, "REJECTED_SECRET_IN_PROPOSAL")
    # target must resolve to an allowed adapter + scope
    target = proposal.get("target", {})
    adapter = target.get("adapter")
    path = target.get("path", "")
    if adapter not in ALLOWED_ADAPTERS:
        return ProposalValidationResult(False, "REJECTED_ADAPTER_NOT_ALLOWED")
    if not path.startswith(ALLOWED_ROOT) or ".." in path:
        return ProposalValidationResult(False, "REJECTED_TARGET_OUT_OF_SCOPE")
    # reject direct shell strings masquerading as a file op
    if any(k in proposal for k in ("shell", "command", "argv")):
        return ProposalValidationResult(False, "REJECTED_DIRECT_SHELL")
    # evidence required
    if not proposal.get("evidence_refs"):
        return ProposalValidationResult(False, "REJECTED_MISSING_EVIDENCE")

    # 4/5. STRIP authority markers anywhere the proposer supplied them
    stripped = sorted(k for k in proposal if k.lower() in AUTHORITY_MARKERS)

    # 8/9. mint a FRESH canonical ActionSpec — authority comes ONLY from the spine, never the proposal
    payload = {"adapter": adapter, "path": path, "content_sha256": proposal.get("content_sha256"),
               "op": "write_file"}
    action_spec = {
        "schema_version": "1.0",
        "action_id": str(uuid.uuid4()),
        "tool": "filesystem",
        "operation": "write_file",
        "data_class": proposal.get("data_class", "INTERNAL"),
        "target": payload,
        "trace": {"source_trace_id": proposal["source_trace_id"], "brain_run_id": proposal["brain_run_id"]},
        "idempotency_key": hashlib.sha256((pid + path).encode()).hexdigest()[:32],
        "origin": "proposal_bridge",   # never "brain"; authority not inherited
    }
    seen_ids.add(pid)
    return ProposalValidationResult(True, "OK", action_spec, stripped)
