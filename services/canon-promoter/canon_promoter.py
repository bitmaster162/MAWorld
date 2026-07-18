"""Fail-closed tombstone for the retired v1 canon promoter.

The old service imported a live ContinuityOS tree, held both promoter and
human-approval secrets, accepted caller booleans as evidence/policy, and used
in-memory replay state.  It is intentionally incapable of issuing approval,
issuing a workload credential, unlocking ContinuityOS, or materializing canon.

Use ``maworld_core.canon_sod.CanonPromoter`` (re-exported by ``canon_sod.py``)
with an external verify-only approval function and durable state.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass


LEGACY_DISABLED_REASON = "LEGACY_CANON_PROMOTER_DISABLED_USE_CANON_SOD"


class LegacyCanonPromoterDisabled(RuntimeError):
    """The authority-bearing legacy operation has been permanently removed."""


class CanonWriteForbidden(LegacyCanonPromoterDisabled):
    pass


class GuardedContinuity:
    """Non-writing compatibility object; it never imports ContinuityOS."""

    def __init__(self, *args, **kwargs):
        # Do not retain a live Continuity object, Memory, DB path, or callback.
        pass

    def add_canon(self, text, tags=None):
        raise CanonWriteForbidden(LEGACY_DISABLED_REASON)


@dataclass(frozen=True)
class CanonCandidate:
    """Pure legacy data shape retained only to make stale callers fail clearly."""

    candidate_id: str
    project_id: str
    statement: str
    source_decision_id: str
    source_decision: dict
    supersedes_canon_id: int | None = None

    @property
    def source_decision_hash(self) -> str:
        body = json.dumps(
            self.source_decision,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
        return hashlib.sha256(body).hexdigest()


@dataclass(frozen=True)
class PromotionResult:
    decision: str
    reason: str
    canon_id: int | None = None
    superseded: int | None = None


def sign(*args, **kwargs):
    """Removed: the legacy module must hold no signing capability."""
    raise LegacyCanonPromoterDisabled(LEGACY_DISABLED_REASON)


class CanonPromoter:
    """Compatibility tombstone that cannot approve or write canon."""

    def __init__(self, *args, **kwargs):
        # In particular, discard rather than retain promoter_secret,
        # human_secret, Continuity, Ledger, or injected side-effect objects.
        pass

    def make_human_approval(self, *args, **kwargs):
        raise LegacyCanonPromoterDisabled(LEGACY_DISABLED_REASON)

    def promoter_credential(self, *args, **kwargs):
        raise LegacyCanonPromoterDisabled(LEGACY_DISABLED_REASON)

    def promote(self, *args, **kwargs) -> PromotionResult:
        return PromotionResult(
            decision="DENY_LEGACY_DISABLED",
            reason=LEGACY_DISABLED_REASON,
        )
