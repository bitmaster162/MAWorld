"""Fail-closed compatibility surface for the retired side-effect adapter spike.

This service used to accept a bare string such as ``"fs.write"`` as proof of
authority.  A caller could therefore mint its own authority and trigger a file
write.  The implementation is intentionally disabled: production effects must
flow through ``maworld_core.action_authority`` and
``maworld_core.hardened_effect_registry`` with an externally issued, exact
ActionSpec-bound decision.

The old classes remain importable so stale callers fail safely and receive a
clear migration reason.  No method in this module writes files, deletes files,
opens a network connection, invokes a callback, or opens the legacy effect DB.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


LEGACY_DISABLED_REASON = (
    "LEGACY_SIDE_EFFECT_API_DISABLED_USE_ACTION_AUTHORITY_"
    "AND_HARDENED_EFFECT_REGISTRY"
)


class LegacySideEffectDisabled(RuntimeError):
    """Raised when code bypasses the registry and calls an adapter directly."""


@dataclass(frozen=True)
class AdapterResult:
    decision: str
    reason: str
    evidence: dict = field(default_factory=dict)
    effect_id: str | None = None


class SideEffectAdapter(ABC):
    name: str = "abstract"
    required_capability: str = ""
    reversibility_class: str = "UNKNOWN"
    allowed_operations: frozenset[str] = frozenset()
    default_timeout_s: int = 15

    @abstractmethod
    def _perform(self, spec: dict) -> dict:
        """Always fail: direct execution bypasses the canonical authority path."""

    def rollback(self, spec: dict, evidence: dict) -> str:
        # Deletion/compensation is also an external effect and needs fresh,
        # exact authority.  The retired API cannot provide that authority.
        return LEGACY_DISABLED_REASON

    def validate(self, spec: dict) -> tuple[bool, str]:
        if spec.get("operation") not in self.allowed_operations:
            return False, "OPERATION_NOT_ALLOWED"
        return True, "OK"


class FilesystemAdapter(SideEffectAdapter):
    name = "filesystem"
    required_capability = "fs.write"
    reversibility_class = "COMPENSATABLE"
    allowed_operations = frozenset({"write_file"})

    def __init__(self, root):
        # Keep only a normalized scope for diagnostics/validation.  Construction
        # does not create the path or open any filesystem handle.
        self.root = os.path.realpath(os.fspath(root))

    def validate(self, spec):
        ok, reason = super().validate(spec)
        if not ok:
            return ok, reason
        try:
            path = spec["target"]["path"]
            resolved = os.path.realpath(os.fspath(path))
        except (KeyError, TypeError, ValueError):
            return False, "MALFORMED_TARGET"
        if not (resolved == self.root or resolved.startswith(self.root + os.sep)):
            return False, "PATH_OUT_OF_SCOPE"
        return True, "OK"

    def _perform(self, spec):
        raise LegacySideEffectDisabled(LEGACY_DISABLED_REASON)

    def rollback(self, spec, evidence):
        return LEGACY_DISABLED_REASON


class NetworkAdapter(SideEffectAdapter):
    name = "network"
    required_capability = "net.egress"
    reversibility_class = "IRREVERSIBLE"
    allowed_operations = frozenset({"http_post"})

    def __init__(self, allowlist):
        self.allowlist = frozenset(allowlist)

    def validate(self, spec):
        ok, reason = super().validate(spec)
        if not ok:
            return ok, reason
        try:
            host = spec["target"]["host"]
        except (KeyError, TypeError):
            return False, "MALFORMED_TARGET"
        if host not in self.allowlist:
            return False, "HOST_NOT_IN_ALLOWLIST"
        return True, "OK"

    def _perform(self, spec):
        raise LegacySideEffectDisabled(LEGACY_DISABLED_REASON)


class AdapterRegistry:
    """Import-compatible tombstone for the unsafe legacy registry.

    ``redeemed_capability`` is deliberately ignored.  In particular, knowing
    the old capability name never grants authority.
    """

    def __init__(self, effect_db, audit_fn=None):
        # Do not open/create effect_db and do not retain/invoke an arbitrary
        # callback from an authority-less execution request.
        self._adapters: dict[str, SideEffectAdapter] = {}

    def register(self, adapter):
        self._adapters[adapter.name] = adapter

    def execute(self, action_spec: dict, redeemed_capability=None):
        return AdapterResult("HOLD", LEGACY_DISABLED_REASON)

    def close(self):
        return None
