"""Authority-first BitEvo code-execution bridge.

Arbitrary code is accepted only with an exact signed Action Authority decision,
a separate signed human confirmation, and a fixed isolation backend supplied at
construction.  POSIX resource limits alone are not accepted as isolation.  If a
runsc/VM/AppContainer-style backend is absent, the bridge denies before executing
code.  The module owns no gate/human signing key and exposes no per-call runner.
"""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import asdict, dataclass
from typing import Callable

from maworld_core.policy_engine import PolicyEngine
from maworld_core.action_authority import (
    ActionExecutor,
    ActionSpec,
    ActionVerifier,
    ConfusedDeputy,
    Decision,
    HumanConfirmation,
    SQLiteNonceStore,
    execute,
)
from maworld_core.dlp_redact import redact
from maworld_core.article12_export import Article12Record, ComplianceLog
from maworld_core.multimodal_guard import SECRET_FILES
from maworld_core.input_guard import scan


HANDLER_ID = "bitevo.isolated-code/v1"
CapabilityVerifyFn = Callable[[str, str, str, str], bool]

_DANGER = re.compile(
    r"(open\(['\"].*\.env|/secrets?/|subprocess|socket\.|urllib|requests\.|"
    r"os\.system|__import__\(['\"]os)",
    re.I,
)


def _scan_code(code: str) -> list[str]:
    hits = []
    if SECRET_FILES.search(code):
        hits.append("secret-file access")
    if _DANGER.search(code):
        hits.append("egress/secret/subprocess")
    if scan(code)["injection"]:
        hits.append("injection marker")
    return hits


@dataclass(frozen=True)
class IsolationResult:
    ok: bool
    stdout: str = ""
    stderr: str = ""
    signal: int = 0


class IsolatedCodeRunner:
    """Trusted adapter contract for a real filesystem/network isolation backend."""

    backend_id = ""

    def run(self, code: str) -> IsolationResult:
        raise NotImplementedError


class BitEvoBridge:
    def __init__(
        self,
        capability_verify: CapabilityVerifyFn,
        policy: PolicyEngine,
        compliance: ComplianceLog,
        authority_verifier: ActionVerifier,
        nonce_store: SQLiteNonceStore,
        isolation_runner: IsolatedCodeRunner | None = None,
        *,
        max_code_bytes: int = 256 * 1024,
    ):
        if not callable(capability_verify):
            raise TypeError("capability_verify must be callable")
        if not isinstance(policy, PolicyEngine):
            raise TypeError("policy must be fixed at construction")
        if not isinstance(compliance, ComplianceLog):
            raise TypeError("compliance log must be fixed at construction")
        if not isinstance(authority_verifier, ActionVerifier):
            raise TypeError("verifier-only ActionVerifier required")
        if not isinstance(nonce_store, SQLiteNonceStore):
            raise TypeError("durable SQLiteNonceStore required")
        if isolation_runner is not None and (
            not isinstance(isolation_runner, IsolatedCodeRunner)
            or not isinstance(isolation_runner.backend_id, str)
            or not isolation_runner.backend_id
        ):
            raise TypeError("isolation_runner must be an identified IsolatedCodeRunner")
        if not isinstance(max_code_bytes, int) or max_code_bytes <= 0:
            raise ValueError("max_code_bytes must be positive")
        self._capability_verify = capability_verify
        self._policy = policy
        self._compliance = compliance
        self._runner = isolation_runner
        self._max_code_bytes = max_code_bytes
        self._executor = (
            ActionExecutor(
                {HANDLER_ID: self._execute_isolated}, authority_verifier, nonce_store
            )
            if isolation_runner is not None else None
        )

    def action_spec(self, agent_id: str, code: str) -> ActionSpec:
        if not isinstance(agent_id, str) or not agent_id:
            raise ValueError("agent_id required")
        if not isinstance(code, str):
            raise TypeError("code must be a string")
        if len(code.encode("utf-8")) > self._max_code_bytes:
            raise ValueError("code exceeds configured maximum")
        return ActionSpec(
            "code.exec", agent_id, (code,), handler_id=HANDLER_ID
        )

    def _execute_isolated(self, spec: ActionSpec) -> dict:
        result = self._runner.run(spec.params[0])
        if not isinstance(result, IsolationResult):
            raise RuntimeError("isolation backend returned an invalid result")
        return asdict(result)

    def _log(self, agent: str, code_hash: str, decision: str, outcome: str = "") -> None:
        self._compliance.append(Article12Record(
            agent_id=agent or "unknown",
            action="bitevo.execute_code",
            event_time=time.time(),
            decision=decision,
            capability_ref="cap-execute",
            risk_level="HIGH",
            evidence_ref=code_hash[:12],
            outcome=outcome,
        ))

    def _deny(self, agent: str, code_hash: str, reason: str) -> dict:
        self._log(agent, code_hash, "DENY", reason)
        return {
            "admitted": False,
            "sandboxed": False,
            "reason": reason,
            "authoritative": False,
        }

    def admit(
        self,
        passport: dict,
        code: str,
        decision: Decision | None,
        confirmation: HumanConfirmation | None = None,
    ) -> dict:
        if not isinstance(passport, dict) or not isinstance(code, str):
            raise TypeError("passport must be a dict and code must be a string")
        agent = passport.get("agent_id", "")
        code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
        try:
            spec = self.action_spec(agent, code)
        except (TypeError, ValueError) as exc:
            return self._deny(agent, code_hash, f"invalid action: {exc}")
        try:
            capability_ok = bool(self._capability_verify(
                passport.get("token", ""), agent, "execute_code", "sandbox"
            ))
        except Exception:
            capability_ok = False
        if not capability_ok:
            return self._deny(agent, code_hash, "invalid/forged capability passport")
        if not self._policy.evaluate(agent, "execute_code", "sandbox").allow:
            return self._deny(agent, code_hash, "policy denied execute_code")
        hits = _scan_code(code)
        if hits:
            return self._deny(
                agent, code_hash, "dangerous code: " + ", ".join(hits)
            )
        if self._executor is None:
            return self._deny(
                agent,
                code_hash,
                "isolation backend unavailable; resource limits alone are not a sandbox",
            )
        if not isinstance(decision, Decision):
            return self._deny(agent, code_hash, "signed action decision required")
        if decision.verdict != "REQUIRE_CONFIRMATION":
            return self._deny(
                agent,
                code_hash,
                "arbitrary code requires REQUIRE_CONFIRMATION verdict",
            )
        try:
            output = execute(spec, decision, self._executor, confirmation=confirmation)
        except ConfusedDeputy as exc:
            return self._deny(agent, code_hash, "authority: " + str(exc))
        except Exception as exc:
            return self._deny(
                agent, code_hash, "isolation backend failure: " + type(exc).__name__
            )
        result = output["result"]
        self._log(agent, code_hash, "ALLOW", "isolated execution admitted")
        return {
            "admitted": True,
            "ok": bool(result.get("ok")),
            "code_hash": code_hash[:12],
            "sandboxed": True,
            "isolation_backend": self._runner.backend_id,
            "stdout": redact(result.get("stdout", "")),
            "stderr": redact(result.get("stderr", "")),
            "signal": result.get("signal", 0),
            "authoritative": False,
        }


def admit_bitevo_code(*_args, **_kwargs) -> dict:
    """Removed insecure compatibility path; it cannot mint its own authority."""
    return {
        "admitted": False,
        "sandboxed": False,
        "reason": "explicit BitEvoBridge, external decision, and isolation backend required",
        "authoritative": False,
    }
