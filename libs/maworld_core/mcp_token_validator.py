"""Audience-bound MCP bearer tokens with an explicit verifier boundary.

Signing and verification are deliberately separate roles.  An authorization
service receives :class:`MCPTokenIssuer`; an MCP server receives one
:class:`MCPTokenVerifier` whose issuer keys, audience, scopes, origin policy,
clock and lifetime limits are copied and fixed at construction.  A request can
only supply the token and its observed origin.

HMAC is used here to keep the local adversarial suite self-contained.  A
production deployment should replace it with asymmetric, externally-custodied
issuer keys while preserving this verifier-only API shape.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import time
from types import MappingProxyType
from typing import Callable, Mapping


TOKEN_DOMAIN = b"MAWORLD/MCP-AUTH/TOKEN/V1\x00"
TOKEN_VERSION = 1

_CLAIMS = frozenset({"version", "aud", "iss", "scope", "iat", "exp", "sub"})
_MAX_TOKEN_BYTES = 16 * 1024
_MAX_TTL_S = 3600
_MAX_FUTURE_SKEW_S = 5
_MIN_HMAC_KEY_BYTES = 32


class MCPAuthError(Exception):
    """Fail-closed authentication error suitable for a 401 response."""

    def __init__(self, message: str):
        super().__init__(message)
        self.http = 401


def _required_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _copy_key(name: str, value: object) -> bytes:
    if not isinstance(value, bytes) or len(value) < _MIN_HMAC_KEY_BYTES:
        raise ValueError(
            f"{name} must be bytes with at least {_MIN_HMAC_KEY_BYTES} bytes"
        )
    return bytes(value)


def _copy_scope_set(name: str, values: object) -> frozenset[str]:
    if not isinstance(values, (set, frozenset)) or not values:
        raise ValueError(f"a fixed non-empty {name} is required")
    copied = frozenset(values)
    if any(not isinstance(value, str) or not value.strip() for value in copied):
        raise ValueError(f"{name} is invalid")
    return copied


def _copy_origins(values: object) -> frozenset[str]:
    copied = _copy_scope_set("origin allowlist", values)
    if any(" " in origin for origin in copied):
        raise ValueError("origin allowlist is invalid")
    return copied


def _ttl(value: object) -> int:
    if not _is_int(value) or not 0 < value <= _MAX_TTL_S:
        raise ValueError(f"ttl_s must be in 1..{_MAX_TTL_S}")
    return value


def _encode_claims(claims: Mapping[str, object]) -> bytes:
    return json.dumps(
        claims,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _b64_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64_decode(raw: str) -> bytes:
    if not raw or not raw.isascii() or "=" in raw:
        raise ValueError("non-canonical base64url")
    padded = raw + "=" * (-len(raw) % 4)
    decoded = base64.b64decode(padded, altchars=b"-_", validate=True)
    if _b64_encode(decoded) != raw:
        raise ValueError("non-canonical base64url")
    return decoded


def _json_object_without_duplicates(raw: bytes) -> dict:
    def reject_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON claim")
            result[key] = value
        return result

    value = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicates)
    if not isinstance(value, dict):
        raise ValueError("token payload must be an object")
    return value


class MCPTokenIssuer:
    """Sign-only issuer with a fixed issuer identity and signing key."""

    __slots__ = ("issuer_id", "__signing_key", "_clock")

    def __init__(
        self,
        issuer_id: str,
        signing_key: bytes,
        *,
        clock: Callable[[], float] = time.time,
    ):
        self.issuer_id = _required_text("issuer_id", issuer_id)
        self.__signing_key = _copy_key("signing_key", signing_key)
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._clock = clock

    def issue(
        self,
        *,
        audience: str,
        scope: str,
        ttl_s: int = 300,
        subject: str = "agent",
    ) -> str:
        audience = _required_text("audience", audience)
        scope = _required_text("scope", scope)
        subject = _required_text("subject", subject)
        ttl_s = _ttl(ttl_s)
        issued_at = self._clock()
        if (
            isinstance(issued_at, bool)
            or not isinstance(issued_at, (int, float))
            or not math.isfinite(issued_at)
        ):
            raise ValueError("issuer clock returned an invalid time")
        issued_at = int(issued_at)
        claims = {
            "version": TOKEN_VERSION,
            "aud": audience,
            "iss": self.issuer_id,
            "scope": scope,
            "iat": issued_at,
            "exp": issued_at + ttl_s,
            "sub": subject,
        }
        encoded = _b64_encode(_encode_claims(claims))
        signature = hmac.new(
            self.__signing_key,
            TOKEN_DOMAIN + encoded.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        return encoded + "." + signature


class MCPTokenVerifier:
    """Verifier-only policy fixed by the trusted MCP server composition root."""

    __slots__ = (
        "__issuer_keys",
        "_server_uri",
        "_required_scopes",
        "_origin_allowlist",
        "_clock",
        "_max_ttl_s",
        "_max_future_skew_s",
        "__sealed",
    )

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_MCPTokenVerifier__sealed", False):
            raise AttributeError("MCPTokenVerifier trust policy is immutable")
        object.__setattr__(self, name, value)

    def __init__(
        self,
        issuer_keys: Mapping[str, bytes],
        *,
        this_server_uri: str,
        required_scopes: set[str] | frozenset[str],
        origin_allowlist: set[str] | frozenset[str],
        clock: Callable[[], float] = time.time,
        max_ttl_s: int = 300,
        max_future_skew_s: int = _MAX_FUTURE_SKEW_S,
    ):
        if not isinstance(issuer_keys, Mapping) or not issuer_keys:
            raise ValueError("a fixed non-empty issuer key map is required")
        copied_keys = {
            _required_text("issuer_id", issuer_id): _copy_key(
                "issuer verification key", key
            )
            for issuer_id, key in dict(issuer_keys).items()
        }
        self.__issuer_keys = MappingProxyType(copied_keys)
        self._server_uri = _required_text("this_server_uri", this_server_uri)
        self._required_scopes = _copy_scope_set("required scope set", required_scopes)
        self._origin_allowlist = _copy_origins(origin_allowlist)
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._clock = clock
        self._max_ttl_s = _ttl(max_ttl_s)
        if not _is_int(max_future_skew_s) or max_future_skew_s < 0:
            raise ValueError("max_future_skew_s must be a non-negative integer")
        self._max_future_skew_s = max_future_skew_s
        self.__sealed = True

    def validate(self, token: str, *, origin: str) -> dict:
        """Validate using only fixed trust policy and the observed request origin."""
        if not isinstance(origin, str) or origin not in self._origin_allowlist:
            raise MCPAuthError("origin not in fixed allowlist")
        if not isinstance(token, str) or not token or len(token) > _MAX_TOKEN_BYTES:
            raise MCPAuthError("malformed token")

        try:
            encoded, signature = token.rsplit(".", 1)
            if len(signature) != hashlib.sha256().digest_size * 2:
                raise ValueError("invalid signature encoding")
            int(signature, 16)
            claims = _json_object_without_duplicates(_b64_decode(encoded))
        except Exception as exc:
            raise MCPAuthError("malformed token") from exc

        if frozenset(claims) != _CLAIMS or claims.get("version") != TOKEN_VERSION:
            raise MCPAuthError("malformed token claims")
        issuer_id = claims.get("iss")
        if not isinstance(issuer_id, str) or not issuer_id:
            raise MCPAuthError("malformed issuer")
        verification_key = self.__issuer_keys.get(issuer_id)
        if verification_key is None:
            raise MCPAuthError("untrusted issuer")
        expected_signature = hmac.new(
            verification_key,
            TOKEN_DOMAIN + encoded.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected_signature):
            raise MCPAuthError("bad signature")

        if claims.get("aud") != self._server_uri:
            raise MCPAuthError("token is not audience-bound to this MCP server")
        subject = claims.get("sub")
        scope = claims.get("scope")
        issued_at = claims.get("iat")
        expires_at = claims.get("exp")
        if (
            not isinstance(subject, str)
            or not subject
            or not isinstance(scope, str)
            or not scope
            or not _is_int(issued_at)
            or not _is_int(expires_at)
        ):
            raise MCPAuthError("malformed token claims")

        token_scopes = frozenset(scope.split())
        if not token_scopes or not self._required_scopes.issubset(token_scopes):
            raise MCPAuthError("insufficient scope")
        if expires_at <= issued_at or expires_at - issued_at > self._max_ttl_s:
            raise MCPAuthError("token lifetime exceeds fixed policy")

        try:
            now = self._clock()
        except Exception as exc:
            raise MCPAuthError("verifier clock unavailable") from exc
        if (
            isinstance(now, bool)
            or not isinstance(now, (int, float))
            or not math.isfinite(now)
        ):
            raise MCPAuthError("verifier clock unavailable")
        now = int(now)
        if issued_at > now + self._max_future_skew_s:
            raise MCPAuthError("token issued in the future")
        if now >= expires_at:
            raise MCPAuthError("token expired")
        return {"ok": True, "sub": subject, "scope": scope}


def validate(*_args, **_kwargs):
    """Removed unsafe API: caller-provided trust policy always fails closed."""
    raise MCPAuthError(
        "legacy validate API disabled; use a server-owned MCPTokenVerifier"
    )


def mint(*_args, **_kwargs):
    """Removed per-call key/issuer API; use a sign-only MCPTokenIssuer."""
    raise RuntimeError("legacy mint API disabled; use MCPTokenIssuer.issue")


__all__ = [
    "MCPAuthError",
    "MCPTokenIssuer",
    "MCPTokenVerifier",
    "TOKEN_DOMAIN",
    "TOKEN_VERSION",
    "mint",
    "validate",
]
