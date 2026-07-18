"""MCP-aware preflight normalizer (control spine v1).

Verified facts (official changelog https://modelcontextprotocol.io/specification/2025-11-25/changelog):
  2025-11-25 = latest FINALIZED spec: Streamable HTTP, Origin 403 validation,
  OAuth 2.0 Protected Resource Metadata (RFC 9728), incremental scope via WWW-Authenticate,
  experimental `tasks` (durable, polling, deferred results), token passthrough forbidden.
  2026-07-28 = RELEASE CANDIDATE (provisional, stateless) -> gate must NOT freeze behavior on it.

This normalizer runs BEFORE ContinuityOS preflight(): it turns raw MCP transport/auth metadata
into a typed block, rejects spoofed/unknown headers, version-gates, forbids token passthrough,
and treats an accepted async task as NOT complete. Final gate decision = stricter(mcp, policy).
"""
from __future__ import annotations
from dataclasses import dataclass, field

SUPPORTED_VERSIONS = {"2025-11-25"}           # finalized, enforced baseline
KNOWN_PROVISIONAL = {"2026-07-28", "draft"}   # RC / unarchived -> HOLD, do not freeze behavior
# headers the gate understands; anything else MCP-* is untrusted and must not be forwarded
ALLOWED_MCP_HEADERS = {
    "mcp-protocol-version", "mcp-session-id", "origin", "accept",
    "www-authenticate", "mcp-task-id",
}
_ORDER = ["ALLOW", "WARN", "HOLD", "REQUIRE_CONFIRMATION", "DENY"]


def _stricter(a: str, b: str) -> str:
    return a if _ORDER.index(a) >= _ORDER.index(b) else b


@dataclass
class McpNormalized:
    decision: str = "ALLOW"
    reasons: list = field(default_factory=list)
    block: dict = field(default_factory=dict)   # normalized ActionSpec.mcp (v1.2 shape)

    def _raise(self, decision, reason):
        self.decision = _stricter(self.decision, decision)
        self.reasons.append(reason)


def normalize_mcp(meta: dict) -> McpNormalized:
    """meta: request metadata with keys headers(dict), transport, oauth(dict), task(dict)."""
    out = McpNormalized()
    headers = {k.lower(): v for k, v in (meta.get("headers") or {}).items()}

    # 1. reject unknown/spoofed MCP-* headers rather than forwarding blindly
    for h in headers:
        if h.startswith("mcp-") and h not in ALLOWED_MCP_HEADERS:
            out._raise("DENY", f"unknown MCP header rejected: {h}")

    # 2. protocol-version gating
    ver = headers.get("mcp-protocol-version")
    if ver is None:
        out._raise("HOLD", "missing MCP-Protocol-Version")
    elif ver in KNOWN_PROVISIONAL:
        out._raise("HOLD", f"protocol {ver} is release-candidate/unarchived -> HOLD (no behavior freeze)")
    elif ver not in SUPPORTED_VERSIONS:
        out._raise("HOLD", f"unsupported MCP-Protocol-Version {ver}")

    # 3. Streamable HTTP Origin validation (spec: 403 on invalid origin)
    transport = meta.get("transport", "streamable_http")
    if transport == "streamable_http":
        origin = headers.get("origin")
        allowed_origins = meta.get("allowed_origins", [])
        if not origin or (allowed_origins and origin not in allowed_origins):
            out._raise("DENY", "invalid/missing Origin for streamable_http (403)")

    # 4. OAuth: token passthrough forbidden; audience must be bound to this resource server
    oauth = meta.get("oauth") or {}
    resource_server = oauth.get("resource_server_uri")
    token_aud = oauth.get("token_audience")
    if oauth.get("operator_bearer_forwarded"):
        out._raise("DENY", "token passthrough forbidden: operator bearer must not reach MCP server")
    if token_aud is not None and resource_server is not None and token_aud != resource_server:
        out._raise("DENY", f"audience mismatch: token aud {token_aud} != resource {resource_server}")
    # incremental scope challenge (401 + WWW-Authenticate) -> HOLD, not silent retry
    if oauth.get("scope_challenge"):
        out._raise("HOLD", "incremental scope challenge -> new policy decision required (HOLD)")

    # 5. experimental tasks: accepted/created != complete. Downstream mutation must wait for verified result.
    task = meta.get("task") or {}
    task_state = task.get("state", "none")
    if task_state in ("created", "running"):
        out._raise("HOLD", f"MCP task {task_state}: acceptance is not completion -> HOLD until verified result")

    out.block = {
        "protocol_version": ver,
        "transport_mode": transport,
        "session_id_hash": _hash(headers.get("mcp-session-id")),
        "origin": headers.get("origin"),
        "resource_server_uri": resource_server,
        "oauth": {
            "audience_validated": bool(token_aud and resource_server and token_aud == resource_server),
            "token_passthrough_forbidden": True,
        },
        "task": {"state": task_state, "id": task.get("id")},
    }
    return out


def _hash(v):
    if not v:
        return None
    import hashlib
    return hashlib.sha256(v.encode()).hexdigest()[:16]
