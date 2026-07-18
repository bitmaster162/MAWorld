"""Fail-closed tombstone for the retired external dialectic integration.

The former adapter prepended a caller-provided directory to ``sys.path``,
imported and executed a ``mind`` package from that directory, and allowed the
external synthesizer to write a report through its runtime configuration.
Those operations cannot establish a trustworthy security boundary and have
been removed.

This module performs no dynamic import, path mutation, environment mutation,
ContinuityOS access, or filesystem I/O.  It deliberately produces no findings
or canon proposals.  A future integration needs a pinned package, an isolated
runner, accepted evidence, and a non-authoritative proposal boundary.
"""
from __future__ import annotations

from dataclasses import dataclass, field


EXTERNAL_DIALECTIC_DISABLED = (
    "EXTERNAL_DIALECTIC_INTEGRATION_DISABLED_REQUIRES_PINNED_ISOLATED_EVIDENCE_PATH"
)


class ExternalDialecticDisabled(RuntimeError):
    """Raised before any legacy external module or side effect is reached."""


@dataclass(frozen=True)
class AdjudicationFinding:
    """Pure compatibility data shape; it carries no authority."""

    thesis_id: str
    attack: str
    verdict: str
    priority: str
    disposition: str
    authoritative: bool = field(default=False, init=False)
    detail: dict = field(default_factory=dict)


def _disabled() -> None:
    raise ExternalDialecticDisabled(EXTERNAL_DIALECTIC_DISABLED)


def _load_real_dialectic(continuity_os_dir: str):
    """Removed compatibility entry point; never mutates ``sys.path`` or imports."""
    _disabled()


def run_adjudication(continuity_os_dir: str) -> list[AdjudicationFinding]:
    """Fail before I/O; no fake/empty-success findings are returned."""
    _disabled()


def to_canon_candidates(findings: list[AdjudicationFinding]) -> list[dict]:
    """The retired integration cannot create even a proposed canon candidate."""
    _disabled()
