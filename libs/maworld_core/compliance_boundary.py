"""Fail-closed compliance boundary with externally verifiable authority receipts.

Every crossing is bound to an exact :class:`ActionSpec` and an externally signed
Action Authority decision.  High-impact actions require a separately signed human
confirmation.  The decision nonce is consumed in a durable store, and every ALLOW
or DENY receipt is signed over its complete canonical body by a dedicated receipt
issuer.  This module owns no signing secret and trusts no confirmation boolean.

The capability reference is cryptographically bound to the decision, but remains
a reference: the trusted gate is responsible for validating the underlying grant.
"""
from __future__ import annotations

import copy
import hashlib
import json
import time
from dataclasses import asdict, dataclass
from types import MappingProxyType
from typing import Callable, Mapping

from maworld_core.action_authority import (
    ActionSpec,
    ActionVerifier,
    ConfusedDeputy,
    Decision,
    HumanConfirmation,
    SQLiteNonceStore,
)
from maworld_core.input_guard import admit_input
from maworld_core.article12_export import Article12Record, ComplianceLog
from maworld_core.arena_ledger import canon_bytes
from maworld_core.arena_compliance import (
    assert_no_autonomy_claim,
    validate_retention,
)


ART50_EFFECTIVE = "2026-08-02"
RECEIPT_DOMAIN = b"MAWORLD/COMPLIANCE-RECEIPT/V1\x00"
BOUNDARY_HANDLER_ID = "compliance.boundary.cross/v1"
_RISK_LEVELS = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
_HIGH_RISK = {"HIGH", "CRITICAL"}

SignFn = Callable[[bytes], str]
VerifyFn = Callable[[bytes, str], bool]


class BoundaryRefusal(RuntimeError):
    pass


def _required(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


@dataclass
class AgentAction:
    agent_id: str
    action: str
    capability_ref: str
    risk_level: str = "LOW"
    payload_text: str = ""
    source: str = "external"
    generates_content: bool = False
    public_interest: bool = False
    high_impact: bool = False


def art50_artifacts(content: str, agent_id: str, public_interest: bool) -> dict:
    """Article 50 metadata marking, with its robustness limit stated explicitly."""
    digest = hashlib.sha256((content or "").encode("utf-8")).hexdigest()
    return {
        "ai_interaction_notice": "You are interacting with an AI system.",
        "watermark": {
            "scheme": "metadata-tag+digest",
            "content_digest": digest,
            "generator": f"maworld:{agent_id}",
            "machine_readable": True,
            "limits": "metadata marking only; robust/survivable watermarking "
                      "(C2PA/SynthID-class) is NOT implemented and must not be claimed",
        },
        "public_interest_label": (
            "AI-generated content on a matter of public interest"
            if public_interest else None
        ),
        "effective_from": ART50_EFFECTIVE,
    }


class ReceiptIssuer:
    """Dedicated receipt-side signer; keep outside untrusted agent processes."""

    _RESERVED = {
        "receipt_version", "receipt_issuer", "receipt_issued_at", "receipt_signature"
    }

    def __init__(self, issuer_id: str, sign: SignFn, *, clock=time.time):
        self.issuer_id = _required("issuer_id", issuer_id)
        if not callable(sign):
            raise TypeError("sign must be callable")
        self.__sign = sign
        self._clock = clock

    def issue(self, body: dict, *, now: int | None = None) -> dict:
        if not isinstance(body, dict) or self._RESERVED.intersection(body):
            raise BoundaryRefusal("receipt body is invalid or contains reserved fields")
        receipt = copy.deepcopy(body)
        receipt.update({
            "receipt_version": 1,
            "receipt_issuer": self.issuer_id,
            "receipt_issued_at": int(self._clock()) if now is None else int(now),
        })
        try:
            signature = self.__sign(RECEIPT_DOMAIN + canon_bytes(receipt))
        except Exception as exc:
            raise BoundaryRefusal("receipt signing failed") from exc
        if not isinstance(signature, str) or not signature:
            raise BoundaryRefusal("receipt signer returned an invalid signature")
        receipt["receipt_signature"] = signature
        return receipt


class ReceiptVerifier:
    """Verifier-only fixed trust map for long-lived compliance receipts."""

    def __init__(self, issuer_verifiers: Mapping[str, VerifyFn]):
        if not issuer_verifiers or any(
            not isinstance(issuer_id, str) or not issuer_id or not callable(verify)
            for issuer_id, verify in issuer_verifiers.items()
        ):
            raise ValueError("a fixed receipt issuer allowlist is required")
        self._verifiers = MappingProxyType(dict(issuer_verifiers))

    def verify(self, receipt: object) -> bool:
        if not isinstance(receipt, dict):
            return False
        if receipt.get("receipt_version") != 1:
            return False
        issuer_id = receipt.get("receipt_issuer")
        signature = receipt.get("receipt_signature")
        issued_at = receipt.get("receipt_issued_at")
        if (
            not isinstance(issuer_id, str) or not issuer_id
            or not isinstance(signature, str) or not signature
            or not isinstance(issued_at, int) or isinstance(issued_at, bool)
        ):
            return False
        verify = self._verifiers.get(issuer_id)
        if verify is None:
            return False
        body = copy.deepcopy(receipt)
        body.pop("receipt_signature", None)
        try:
            return bool(verify(RECEIPT_DOMAIN + canon_bytes(body), signature))
        except Exception:
            return False


class ComplianceBoundary:
    """Policy/evidence boundary.  Agents can propose, never self-authorize."""

    def __init__(
        self,
        containment,
        retention_days: int,
        authority_verifier: ActionVerifier,
        nonce_store: SQLiteNonceStore,
        receipt_issuer: ReceiptIssuer,
        receipt_verifier: ReceiptVerifier,
        algo_trading_context: bool = False,
        log: ComplianceLog | None = None,
        *,
        clock=time.time,
    ):
        validate_retention(retention_days, algo_trading_context)
        if not isinstance(authority_verifier, ActionVerifier):
            raise ValueError("explicit verifier-only ActionVerifier required")
        if not isinstance(nonce_store, SQLiteNonceStore):
            raise ValueError("explicit durable SQLiteNonceStore required")
        if not isinstance(receipt_issuer, ReceiptIssuer):
            raise ValueError("explicit ReceiptIssuer required")
        if not isinstance(receipt_verifier, ReceiptVerifier):
            raise ValueError("explicit verifier-only ReceiptVerifier required")
        self.containment = containment
        self.retention_days = retention_days
        self.algo_trading_context = algo_trading_context
        self.log = log or ComplianceLog()
        self._authority_verifier = authority_verifier
        self._nonce_store = nonce_store
        self._receipt_issuer = receipt_issuer
        self._receipt_verifier = receipt_verifier
        self._clock = clock
        self._receipts: list[dict] = []

    def describe_capability(self, marketing_text: str, governance_disclosed: bool = False) -> bool:
        """Lint marketing copy; this caller assertion never grants action authority."""
        return assert_no_autonomy_claim(marketing_text, governance_disclosed)

    @staticmethod
    def action_spec(act: AgentAction) -> ActionSpec:
        if not isinstance(act, AgentAction):
            raise TypeError("act must be AgentAction")
        _required("agent_id", act.agent_id)
        _required("action", act.action)
        if not isinstance(act.payload_text, str):
            raise ValueError("payload_text must be a string")
        if not isinstance(act.source, str) or not act.source:
            raise ValueError("source must be a non-empty string")
        if any(
            not isinstance(value, bool)
            for value in (act.generates_content, act.public_interest, act.high_impact)
        ):
            raise ValueError("action flags must be booleans")
        risk = act.risk_level.upper() if isinstance(act.risk_level, str) else ""
        if risk not in _RISK_LEVELS:
            raise ValueError("unsupported risk level")
        payload_digest = hashlib.sha256(act.payload_text.encode("utf-8")).hexdigest()
        return ActionSpec(
            action_type=act.action,
            target=act.agent_id,
            params=(
                act.capability_ref,
                risk,
                payload_digest,
                act.source,
                act.generates_content,
                act.public_interest,
                act.high_impact,
            ),
            handler_id=BOUNDARY_HANDLER_ID,
        )

    @staticmethod
    def _authority_proof(
        spec: ActionSpec | None,
        decision: Decision | None,
        confirmation: HumanConfirmation | None,
    ) -> dict:
        return {
            "action_spec": json.loads(spec.canonical()) if spec is not None else None,
            "spec_hash": spec.hash() if spec is not None else None,
            "decision": asdict(decision) if isinstance(decision, Decision) else None,
            "decision_digest": decision.digest() if isinstance(decision, Decision) else None,
            "human_confirmation": (
                asdict(confirmation)
                if isinstance(confirmation, HumanConfirmation) else None
            ),
        }

    def cross(
        self,
        act: AgentAction,
        decision: Decision | None,
        confirmation: HumanConfirmation | None = None,
    ) -> dict:
        """Authorize one exact action and return a fully signed ALLOW or DENY receipt."""
        if not isinstance(act, AgentAction):
            raise TypeError("act must be AgentAction")
        try:
            spec = self.action_spec(act)
        except (TypeError, ValueError) as exc:
            return self._deny(act, f"action: {exc}", None, decision, confirmation)

        try:
            containment = self.containment.admit(act.agent_id, write=True)
        except Exception as exc:
            return self._deny(
                act, f"containment: verifier error {type(exc).__name__}",
                spec, decision, confirmation,
            )
        if not containment.get("admit"):
            return self._deny(
                act, "containment: " + str(containment.get("reason", "denied")),
                spec, decision, confirmation,
            )
        if not isinstance(act.capability_ref, str) or not act.capability_ref.strip():
            return self._deny(
                act, "authority: no capability reference - nothing authorizes this",
                spec, decision, confirmation,
            )
        if not isinstance(decision, Decision):
            return self._deny(
                act, "authority: signed decision required", spec, decision, confirmation
            )

        try:
            self._authority_verifier.authorize(spec, decision, confirmation)
        except ConfusedDeputy as exc:
            return self._deny(
                act, "authority: " + str(exc), spec, decision, confirmation
            )

        effective_high_impact = (
            act.high_impact or act.risk_level.upper() in _HIGH_RISK
        )
        if effective_high_impact and decision.verdict != "REQUIRE_CONFIRMATION":
            return self._deny(
                act,
                "authority: high-impact action requires REQUIRE_CONFIRMATION verdict",
                spec,
                decision,
                confirmation,
            )

        if act.payload_text:
            try:
                input_decision = admit_input(
                    act.payload_text,
                    source=act.source,
                    high_impact=(effective_high_impact and confirmation is None),
                )
            except Exception as exc:
                return self._deny(
                    act, f"input_guard: verifier error {type(exc).__name__}",
                    spec, decision, confirmation,
                )
            if not input_decision.get("admit"):
                return self._deny(
                    act,
                    "input_guard: " + str(input_decision.get("reason", "rejected")),
                    spec,
                    decision,
                    confirmation,
                )

        if not self._nonce_store.consume(decision):
            return self._deny(
                act, "authority: decision nonce replay", spec, decision, confirmation
            )
        return self._allow(act, spec, decision, confirmation)

    def _allow(
        self,
        act: AgentAction,
        spec: ActionSpec,
        decision: Decision,
        confirmation: HumanConfirmation | None,
    ) -> dict:
        authority = self._authority_proof(spec, decision, confirmation)
        statement = hashlib.sha256(canon_bytes({
            "decision": "ALLOW", "agent_id": act.agent_id, "action": act.action,
            "capability_ref": act.capability_ref, "authority": authority,
        })).hexdigest()
        now = self._clock()
        event_time = float(now)
        ledger_hash = self.log.append(Article12Record(
            agent_id=act.agent_id,
            action=act.action,
            event_time=event_time,
            decision="ALLOW",
            capability_ref=act.capability_ref,
            risk_level=act.risk_level.upper(),
            evidence_ref=statement,
            human_oversight=(
                confirmation.approver_id
                if isinstance(confirmation, HumanConfirmation) else ""
            ),
            outcome="allowed",
        ))
        article50 = (
            art50_artifacts(act.payload_text, act.agent_id, act.public_interest)
            if act.generates_content else None
        )
        return self._signed_receipt({
            "decision": "ALLOW",
            "agent_id": act.agent_id,
            "action": act.action,
            "capability_ref": act.capability_ref,
            "risk_level": act.risk_level.upper(),
            "reason": None,
            "statement": statement,
            "ledger_hash": ledger_hash,
            "article12": True,
            "article50": article50,
            "retention_days": self.retention_days,
            "retention_basis": self._retention_basis(),
            "authority": authority,
            "authoritative": False,
            "ts": int(now),
        })

    def _deny(
        self,
        act: AgentAction,
        reason: str,
        spec: ActionSpec | None,
        decision: Decision | None,
        confirmation: HumanConfirmation | None,
    ) -> dict:
        agent_id = act.agent_id if isinstance(act.agent_id, str) and act.agent_id else "unknown"
        action = act.action if isinstance(act.action, str) and act.action else "unknown"
        capability = (
            act.capability_ref
            if isinstance(act.capability_ref, str) and act.capability_ref else "none"
        )
        risk = (
            act.risk_level.upper()
            if isinstance(act.risk_level, str) and act.risk_level.upper() in _RISK_LEVELS
            else "HIGH"
        )
        authority = self._authority_proof(spec, decision, confirmation)
        statement = hashlib.sha256(canon_bytes({
            "decision": "DENY", "agent_id": agent_id, "action": action,
            "capability_ref": capability, "reason": reason, "authority": authority,
        })).hexdigest()
        now = self._clock()
        event_time = float(now)
        ledger_hash = self.log.append(Article12Record(
            agent_id=agent_id,
            action=action,
            event_time=event_time,
            decision="DENY",
            capability_ref=capability,
            risk_level=risk,
            evidence_ref=statement,
            outcome=reason,
        ))
        return self._signed_receipt({
            "decision": "DENY",
            "agent_id": agent_id,
            "action": action,
            "capability_ref": capability,
            "risk_level": risk,
            "reason": reason,
            "statement": statement,
            "ledger_hash": ledger_hash,
            "article12": True,
            "article50": None,
            "retention_days": self.retention_days,
            "retention_basis": self._retention_basis(),
            "authority": authority,
            "authoritative": False,
            "ts": int(now),
        })

    def _signed_receipt(self, body: dict) -> dict:
        receipt = self._receipt_issuer.issue(body)
        if not self._receipt_verifier.verify(receipt):
            raise BoundaryRefusal("receipt issuer/verifier configuration mismatch")
        self._receipts.append(receipt)
        return receipt

    def _retention_basis(self) -> str:
        return (
            "MiFID II RTS 6"
            if self.algo_trading_context else "EU AI Act Art.26(6)"
        )

    def verify_receipt(self, receipt: dict) -> bool:
        return self._receipt_verifier.verify(receipt)

    def export(self) -> dict:
        exported_log = self.log.export()
        return {
            "standard": "EU AI Act Art.12 (bi-temporal audit trail) + Art.50 transparency",
            "art50_effective": ART50_EFFECTIVE,
            "tamper_evident": exported_log["tamper_evident"],
            "records": exported_log["count"],
            "receipts": len(self._receipts),
            "receipts_verifiable": all(
                self._receipt_verifier.verify(receipt) for receipt in self._receipts
            ),
            "allowed": sum(1 for receipt in self._receipts if receipt["decision"] == "ALLOW"),
            "denied": sum(1 for receipt in self._receipts if receipt["decision"] == "DENY"),
            "retention_days": self.retention_days,
            "retention_basis": self._retention_basis(),
            "invariant": "authority stays with the deterministic spine; agents propose only",
        }
