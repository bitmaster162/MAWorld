"""Compatibility import surface for the canonical canon separation-of-duties API."""

from maworld_core.canon_sod import (
    APPROVAL_DOMAIN,
    APPROVAL_VERSION,
    AcceptedApproval,
    ApprovalVerification,
    ApprovalVerifier,
    Approver,
    CandidateEncodingError,
    CanonPromoter,
    CanonSODError,
    LegacyDatabaseRejected,
    LegacyVerifierAPIRejected,
    PolicyBindingError,
    candidate_hash,
)

__all__ = [
    "APPROVAL_DOMAIN",
    "APPROVAL_VERSION",
    "AcceptedApproval",
    "ApprovalVerification",
    "ApprovalVerifier",
    "Approver",
    "CandidateEncodingError",
    "CanonPromoter",
    "CanonSODError",
    "LegacyDatabaseRejected",
    "LegacyVerifierAPIRejected",
    "PolicyBindingError",
    "candidate_hash",
]
