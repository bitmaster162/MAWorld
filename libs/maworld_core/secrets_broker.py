"""Capability-gated secret dispatch with operation-bound requests.

The module owns no signing key and reads no secret from the environment.  A
control-plane service receives :class:`CapabilityIssuer`; the broker receives
only :class:`CapabilityVerifier` with a fixed issuer allowlist.

A capability signs the exact transport operation, HTTP method and logical
endpoint identifier.  At checkout the broker validates a bounded JSON body
with the operation's fixed schema, reconstructs the transport envelope and
stores an immutable copy.  Dispatch accepts only the opaque one-use reference,
so a caller cannot substitute a URL, method, headers or body after checkout.

This in-process implementation requires an atomic durable replay store, but it
is still only suitable for tests/local composition.  Production needs the same
API behind a process boundary, an external secret store, and a shared
transactional replay backend for every replica.  The reflection checks below
cover exact values and a small set of common reversible encodings; they are
defense in depth, not a claim of general DLP.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import sqlite3
import threading
import time
import urllib.parse
import uuid
from dataclasses import asdict, dataclass
from types import MappingProxyType
from typing import Callable, Mapping


CAPABILITY_DOMAIN = b"MAWORLD/SECRETS-BROKER/DISPATCH-CAPABILITY/V2\x00"
CAPABILITY_PURPOSE = "secret_transport_dispatch"
DEFAULT_CAPABILITY_TTL_S = 30
MAX_CAPABILITY_TTL_S = 60
MAX_FUTURE_SKEW_S = 5

MAX_IDENTIFIER_CHARS = 256
MAX_SIGNATURE_CHARS = 2048
MAX_SECRET_CHARS = 4096
MAX_REQUEST_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 256 * 1024
MAX_JSON_STRING_CHARS = 32 * 1024
MAX_JSON_KEY_CHARS = 256
MAX_JSON_DEPTH = 16
MAX_JSON_NODES = 4096
MAX_JSON_CONTAINER_ITEMS = 2048

_OPERATION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})
_RESERVED_REQUEST_FIELDS = frozenset(
    {
        "authorization",
        "endpoint",
        "endpoint_id",
        "headers",
        "host",
        "hostname",
        "http-referer",
        "method",
        "proxy",
        "uri",
        "url",
    }
)

SignFn = Callable[[bytes], str]
VerifyFn = Callable[[bytes, str], bool]
PrepareRequestFn = Callable[[object], object]
TransportFn = Callable[[str, object], object]


class SecretBrokerError(RuntimeError):
    pass


class SecretDispatchError(SecretBrokerError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _required(name: str, value: str, *, max_chars: int = MAX_IDENTIFIER_CHARS) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > max_chars
        or any(ord(char) < 32 for char in value)
    ):
        raise ValueError(f"{name} must be a bounded non-empty string")
    return value


def _operation_identifier(name: str, value: str) -> str:
    value = _required(name, value, max_chars=128)
    if _OPERATION_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be a logical identifier, not a URL or path")
    return value


def _method(value: str) -> str:
    if not isinstance(value, str) or value not in _METHODS:
        raise ValueError("method must be an exact uppercase allowed method")
    return value


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _ttl(ttl_s: int) -> int:
    if not _is_int(ttl_s) or not 0 < ttl_s <= MAX_CAPABILITY_TTL_S:
        raise ValueError(f"ttl_s must be in 1..{MAX_CAPABILITY_TTL_S}")
    return ttl_s


def _bounded_json_copy(value: object, *, max_bytes: int) -> object:
    """Return an alias-free JSON value after hard structural/byte limits."""
    nodes = 0

    def walk(item: object, depth: int) -> object:
        nonlocal nodes
        nodes += 1
        if nodes > MAX_JSON_NODES or depth > MAX_JSON_DEPTH:
            raise ValueError("JSON structure exceeds broker limits")
        if item is None or isinstance(item, bool):
            return item
        if _is_int(item):
            if abs(item) > 9_007_199_254_740_991:
                raise ValueError("integer exceeds interoperable JSON range")
            return item
        if isinstance(item, float):
            if not math.isfinite(item):
                raise ValueError("non-finite JSON number")
            return item
        if isinstance(item, str):
            if len(item) > MAX_JSON_STRING_CHARS:
                raise ValueError("JSON string exceeds broker limit")
            return item
        if isinstance(item, list):
            if len(item) > MAX_JSON_CONTAINER_ITEMS:
                raise ValueError("JSON list exceeds broker limit")
            return [walk(child, depth + 1) for child in item]
        if isinstance(item, dict):
            if len(item) > MAX_JSON_CONTAINER_ITEMS:
                raise ValueError("JSON object exceeds broker limit")
            copied: dict[str, object] = {}
            for key, child in item.items():
                if (
                    not isinstance(key, str)
                    or not key
                    or len(key) > MAX_JSON_KEY_CHARS
                    or any(ord(char) < 32 for char in key)
                ):
                    raise ValueError("invalid JSON object key")
                copied[key] = walk(child, depth + 1)
            return copied
        raise ValueError("transport data must be JSON-like")

    copied = walk(value, 0)
    encoded = _canonical(copied)
    if len(encoded) > max_bytes:
        raise ValueError("JSON payload exceeds broker byte limit")
    # Round-trip once so no caller-owned aliases or exotic subclasses survive.
    return json.loads(encoded)


def _contains_reserved_request_field(value: object) -> bool:
    if isinstance(value, list):
        return any(_contains_reserved_request_field(child) for child in value)
    if isinstance(value, dict):
        return any(
            key.casefold() in _RESERVED_REQUEST_FIELDS
            or _contains_reserved_request_field(child)
            for key, child in value.items()
        )
    return False


@dataclass(frozen=True)
class SecretScope:
    subject_id: str
    secret_id: str
    role: str
    data_class: str
    transport_id: str
    operation_id: str
    method: str
    endpoint_id: str

    def __post_init__(self) -> None:
        for name in ("subject_id", "secret_id", "role", "data_class", "transport_id"):
            _required(name, getattr(self, name))
        _operation_identifier("operation_id", self.operation_id)
        _method(self.method)
        _operation_identifier("endpoint_id", self.endpoint_id)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: object) -> "SecretScope | None":
        if not isinstance(raw, dict) or set(raw) != {
            "subject_id",
            "secret_id",
            "role",
            "data_class",
            "transport_id",
            "operation_id",
            "method",
            "endpoint_id",
        }:
            return None
        try:
            return cls(**raw)
        except (TypeError, ValueError):
            return None


@dataclass(frozen=True)
class TransportOperation:
    """One fixed broker-side operation and its trusted request schema."""

    transport_id: str
    operation_id: str
    method: str
    endpoint_id: str
    prepare_request: PrepareRequestFn
    transport: TransportFn

    def __post_init__(self) -> None:
        _required("transport_id", self.transport_id)
        _operation_identifier("operation_id", self.operation_id)
        _method(self.method)
        _operation_identifier("endpoint_id", self.endpoint_id)
        if not callable(self.prepare_request):
            raise TypeError("prepare_request must be callable")
        if not callable(self.transport):
            raise TypeError("transport must be callable")

    def matches(self, scope: SecretScope) -> bool:
        return (
            self.transport_id == scope.transport_id
            and self.operation_id == scope.operation_id
            and self.method == scope.method
            and self.endpoint_id == scope.endpoint_id
        )


@dataclass(frozen=True)
class CapabilityToken:
    issuer_id: str
    token_id: str
    purpose: str
    scope: SecretScope
    issued_at: int
    expires_at: int
    sig: str = ""

    def _payload(self) -> bytes:
        return _canonical(
            {
                "issuer_id": self.issuer_id,
                "token_id": self.token_id,
                "purpose": self.purpose,
                "scope": self.scope.to_dict(),
                "issued_at": self.issued_at,
                "expires_at": self.expires_at,
            }
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: object) -> "CapabilityToken | None":
        if not isinstance(raw, dict) or set(raw) != {
            "issuer_id",
            "token_id",
            "purpose",
            "scope",
            "issued_at",
            "expires_at",
            "sig",
        }:
            return None
        scope = SecretScope.from_dict(raw.get("scope"))
        if scope is None:
            return None
        values = dict(raw)
        values["scope"] = scope
        try:
            token = cls(**values)
        except TypeError:
            return None
        return token if _well_formed_token(token) else None


def _well_formed_token(token: CapabilityToken) -> bool:
    return (
        isinstance(token.issuer_id, str)
        and 0 < len(token.issuer_id) <= MAX_IDENTIFIER_CHARS
        and isinstance(token.token_id, str)
        and 0 < len(token.token_id) <= 128
        and token.purpose == CAPABILITY_PURPOSE
        and isinstance(token.sig, str)
        and 0 < len(token.sig) <= MAX_SIGNATURE_CHARS
        and isinstance(token.scope, SecretScope)
        and _is_int(token.issued_at)
        and _is_int(token.expires_at)
    )


def _coerce_token(raw: object) -> CapabilityToken | None:
    if isinstance(raw, CapabilityToken):
        return raw if _well_formed_token(raw) else None
    return CapabilityToken.from_dict(raw)


@dataclass(frozen=True)
class CapabilityCheck:
    accepted: bool
    reason: str
    token: CapabilityToken | None = None


class CapabilityIssuer:
    """Sign-only control-plane object; do not place it in an agent process."""

    def __init__(self, issuer_id: str, sign: SignFn, *, clock=time.time):
        self.issuer_id = _required("issuer_id", issuer_id)
        if not callable(sign):
            raise TypeError("sign must be callable")
        self.__sign = sign
        self._clock = clock

    def issue(
        self,
        scope: SecretScope,
        *,
        ttl_s: int = DEFAULT_CAPABILITY_TTL_S,
        now: int | None = None,
    ) -> CapabilityToken:
        if not isinstance(scope, SecretScope):
            raise TypeError("exact SecretScope required")
        ttl_s = _ttl(ttl_s)
        issued_at = int(self._clock()) if now is None else int(now)
        unsigned = CapabilityToken(
            issuer_id=self.issuer_id,
            token_id=uuid.uuid4().hex,
            purpose=CAPABILITY_PURPOSE,
            scope=scope,
            issued_at=issued_at,
            expires_at=issued_at + ttl_s,
        )
        signature = self.__sign(CAPABILITY_DOMAIN + unsigned._payload())
        if (
            not isinstance(signature, str)
            or not signature
            or len(signature) > MAX_SIGNATURE_CHARS
        ):
            raise ValueError("capability signer returned an invalid signature")
        return CapabilityToken(**{**unsigned.__dict__, "sig": signature})


class CapabilityVerifier:
    """Verifier-only policy with a copied, immutable issuer allowlist."""

    def __init__(
        self,
        issuer_verifiers: Mapping[str, VerifyFn],
        *,
        clock=time.time,
        max_ttl_s: int = MAX_CAPABILITY_TTL_S,
        max_future_skew_s: int = MAX_FUTURE_SKEW_S,
    ):
        if not isinstance(issuer_verifiers, Mapping) or not issuer_verifiers:
            raise ValueError("a fixed capability issuer allowlist is required")
        copied = dict(issuer_verifiers)
        if any(
            not isinstance(issuer_id, str)
            or not issuer_id.strip()
            or len(issuer_id) > MAX_IDENTIFIER_CHARS
            or not callable(verify)
            for issuer_id, verify in copied.items()
        ):
            raise ValueError("capability issuer allowlist is invalid")
        if not _is_int(max_ttl_s) or not 1 <= max_ttl_s <= MAX_CAPABILITY_TTL_S:
            raise ValueError(f"max_ttl_s must be in 1..{MAX_CAPABILITY_TTL_S}")
        if not _is_int(max_future_skew_s) or max_future_skew_s < 0:
            raise ValueError("max_future_skew_s must be a non-negative integer")
        self._verifiers = MappingProxyType(copied)
        self._clock = clock
        self._max_ttl = max_ttl_s
        self._future_skew = max_future_skew_s

    def verify(self, raw: object, expected_scope: SecretScope) -> CapabilityCheck:
        if not isinstance(expected_scope, SecretScope):
            return CapabilityCheck(False, "exact SecretScope required")
        token = _coerce_token(raw)
        if token is None:
            return CapabilityCheck(False, "malformed capability")
        if token.scope != expected_scope:
            return CapabilityCheck(False, "capability scope mismatch")
        verify_signature = self._verifiers.get(token.issuer_id)
        if verify_signature is None:
            return CapabilityCheck(False, "untrusted capability issuer")
        try:
            signature_ok = bool(
                verify_signature(CAPABILITY_DOMAIN + token._payload(), token.sig)
            )
        except Exception:
            signature_ok = False
        if not signature_ok:
            return CapabilityCheck(False, "invalid capability signature")
        now = int(self._clock())
        if (
            token.issued_at > now + self._future_skew
            or now >= token.expires_at
            or token.expires_at <= token.issued_at
            or token.expires_at - token.issued_at > self._max_ttl
        ):
            return CapabilityCheck(False, "invalid capability lifetime")
        return CapabilityCheck(True, "accepted", token)


@dataclass(frozen=True)
class _Checkout:
    scope: SecretScope
    expires_at: int
    request_bytes: bytes
    request_digest: str


class CapabilityReplayStore:
    """Durable atomic one-use store for validated dispatch capabilities."""

    def __init__(self, path: str):
        if not isinstance(path, str) or not path or path == ":memory:":
            raise ValueError("explicit durable capability replay database path required")
        self._connection = sqlite3.connect(
            path, timeout=30, isolation_level=None, check_same_thread=False
        )
        self._lock = threading.Lock()
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=FULL")
        self._connection.execute("PRAGMA busy_timeout=30000")
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS consumed_dispatch_capability(
                token_id TEXT PRIMARY KEY,
                capability_digest TEXT NOT NULL,
                consumed_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL
            )"""
        )

    def consume(
        self,
        token_id: str,
        capability_digest: str,
        consumed_at: int,
        expires_at: int,
    ) -> bool:
        with self._lock:
            cursor = self._connection.execute(
                "INSERT OR IGNORE INTO consumed_dispatch_capability"
                "(token_id,capability_digest,consumed_at,expires_at) VALUES(?,?,?,?)",
                (token_id, capability_digest, consumed_at, expires_at),
            )
        return cursor.rowcount == 1

    def close(self) -> None:
        with self._lock:
            self._connection.close()


def _encoded_secret_markers(secret: str) -> tuple[str, ...]:
    raw = secret.encode("utf-8")
    markers = {
        secret,
        secret.casefold(),
        secret[::-1],
        raw.hex(),
        raw.hex().upper(),
        base64.b64encode(raw).decode("ascii"),
        base64.urlsafe_b64encode(raw).decode("ascii"),
        base64.b32encode(raw).decode("ascii"),
        urllib.parse.quote(secret, safe=""),
    }
    markers |= {marker.rstrip("=") for marker in tuple(markers) if len(marker) >= 8}
    return tuple(marker for marker in markers if marker)


def _text_reflects_secret(
    text: str,
    markers: tuple[str, ...],
    separator_pattern: re.Pattern[str] | None,
) -> bool:
    folded = text.casefold()
    compact = "".join(char for char in folded if not char.isspace())
    for marker in markers:
        if marker in folded:
            return True
        if len(marker) >= 8 and marker in compact:
            return True
    return separator_pattern is not None and separator_pattern.search(text) is not None


def _safe_transport_response(value: object, secret: str) -> bool:
    """Reject known plaintext/common reversible encodings in bounded JSON."""
    markers = tuple(marker.casefold() for marker in _encoded_secret_markers(secret))
    separator_pattern = None
    if 8 <= len(secret) <= 256:
        # Catch trivial separator insertion without pretending to decode
        # arbitrary transformations.  The upper bound keeps this defense from
        # becoming a regular-expression resource attack for huge credentials.
        pattern = r"[\s._:/\\-]*".join(re.escape(char) for char in secret)
        separator_pattern = re.compile(pattern, re.IGNORECASE)

    def walk(item: object) -> bool:
        if isinstance(item, str):
            return not _text_reflects_secret(item, markers, separator_pattern)
        if isinstance(item, list):
            return all(walk(child) for child in item)
        if isinstance(item, dict):
            return all(
                not _text_reflects_secret(key, markers, separator_pattern)
                and walk(child)
                for key, child in item.items()
            )
        return True

    return walk(value)


class SecretsBroker:
    """Verifier-only broker with fixed operations and frozen checkout bodies."""

    def __init__(
        self,
        verifier: CapabilityVerifier,
        trusted_operations: Mapping[str, TransportOperation],
        replay_store: CapabilityReplayStore,
        *,
        clock=time.time,
    ):
        if not isinstance(verifier, CapabilityVerifier):
            raise ValueError("explicit verifier-only CapabilityVerifier required")
        if not isinstance(trusted_operations, Mapping) or not trusted_operations:
            raise ValueError("a fixed trusted operation registry is required")
        if not isinstance(replay_store, CapabilityReplayStore):
            raise ValueError("durable CapabilityReplayStore required")
        operations = dict(trusted_operations)
        if any(
            not isinstance(name, str)
            or not isinstance(operation, TransportOperation)
            or name != operation.operation_id
            for name, operation in operations.items()
        ):
            raise ValueError("trusted operation registry is invalid")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._verifier = verifier
        self._operations = MappingProxyType(operations)
        self._replay = replay_store
        self._clock = clock
        self.__vault: dict[tuple[str, str, str], str] = {}
        self._checkouts: dict[str, _Checkout] = {}
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return (
            f"<SecretsBroker secrets={len(self.__vault)} "
            f"operations={tuple(self._operations)} values=REDACTED>"
        )

    def put(self, secret_id: str, role: str, data_class: str, value: str) -> None:
        """Provision a test/dev secret. Production uses an external store."""
        key = (
            _required("secret_id", secret_id),
            _required("role", role),
            _required("data_class", data_class),
        )
        if not isinstance(value, str) or not value or len(value) > MAX_SECRET_CHARS:
            raise ValueError("secret value must be a bounded non-empty string")
        with self._lock:
            self.__vault[key] = value

    def _prepare(self, operation: TransportOperation, body: object) -> bytes | None:
        try:
            caller_body = _bounded_json_copy(body, max_bytes=MAX_REQUEST_BYTES)
            if _contains_reserved_request_field(caller_body):
                return None
            normalized = operation.prepare_request(caller_body)
            normalized = _bounded_json_copy(normalized, max_bytes=MAX_REQUEST_BYTES)
            if _contains_reserved_request_field(normalized):
                return None
            envelope = _bounded_json_copy(
                {
                    "operation_id": operation.operation_id,
                    "method": operation.method,
                    "endpoint_id": operation.endpoint_id,
                    "body": normalized,
                },
                max_bytes=MAX_REQUEST_BYTES,
            )
            return _canonical(envelope)
        except Exception:
            return None

    def checkout(
        self,
        scope: SecretScope,
        capability: object,
        request_body: object,
    ) -> dict:
        """Consume a capability and freeze one validated operation request."""
        check = self._verifier.verify(capability, scope)
        if not check.accepted or check.token is None:
            return {"ok": False, "reason": "capability rejected"}
        token = check.token
        capability_digest = hashlib.sha256(
            CAPABILITY_DOMAIN + token._payload() + b"\x00" + token.sig.encode("utf-8")
        ).hexdigest()
        try:
            consumed = self._replay.consume(
                token.token_id,
                capability_digest,
                int(self._clock()),
                token.expires_at,
            )
        except (sqlite3.Error, TypeError, ValueError, OverflowError):
            consumed = False
        if not consumed:
            return {"ok": False, "reason": "capability rejected"}
        with self._lock:
            # Consume before local/schema checks: a valid one-use grant never
            # becomes reusable because of a broker configuration error.
            operation = self._operations.get(scope.operation_id)
            configured = (
                operation is not None
                and operation.matches(scope)
                and (scope.secret_id, scope.role, scope.data_class) in self.__vault
            )
        if not configured or operation is None:
            return {"ok": False, "reason": "secret operation unavailable"}
        request_bytes = self._prepare(operation, request_body)
        if request_bytes is None:
            return {"ok": False, "reason": "request rejected"}
        reference = "sref-" + uuid.uuid4().hex
        checkout = _Checkout(
            scope=scope,
            expires_at=token.expires_at,
            request_bytes=request_bytes,
            request_digest=hashlib.sha256(request_bytes).hexdigest(),
        )
        with self._lock:
            self._checkouts[reference] = checkout
        return {"ok": True, "reference": reference, "expires_at": token.expires_at}

    def dispatch(self, reference: str) -> object:
        """Dispatch the exact frozen request; no caller request is accepted."""
        if not isinstance(reference, str) or not reference:
            raise SecretDispatchError("secret dispatch refused")
        with self._lock:
            checkout = self._checkouts.pop(reference, None)
        if checkout is None or int(self._clock()) >= checkout.expires_at:
            raise SecretDispatchError("secret dispatch refused")

        operation = self._operations.get(checkout.scope.operation_id)
        secret = self.__vault.get(
            (checkout.scope.secret_id, checkout.scope.role, checkout.scope.data_class)
        )
        if (
            operation is None
            or not operation.matches(checkout.scope)
            or secret is None
            or hashlib.sha256(checkout.request_bytes).hexdigest()
            != checkout.request_digest
        ):
            secret = None
            raise SecretDispatchError("secret dispatch refused")
        try:
            request = json.loads(checkout.request_bytes)
        except Exception:
            secret = None
            raise SecretDispatchError("secret dispatch refused") from None

        transport_failed = False
        response = None
        bounded_response = None
        try:
            response = operation.transport(secret, request)
        except Exception:
            transport_failed = True
        if not transport_failed:
            try:
                bounded_response = _bounded_json_copy(
                    response, max_bytes=MAX_RESPONSE_BYTES
                )
            except Exception:
                transport_failed = True
        if transport_failed:
            request = None
            response = None
            bounded_response = None
            secret = None
            raise SecretDispatchError("trusted transport failed")
        if not _safe_transport_response(bounded_response, secret):
            request = None
            response = None
            bounded_response = None
            secret = None
            raise SecretDispatchError("trusted transport returned an unsafe response")
        safe_response = bounded_response
        request = None
        response = None
        bounded_response = None
        secret = None
        return safe_response

    def grant(self, *_args, **_kwargs):
        """Removed: the verifier/broker process cannot mint capabilities."""
        raise PermissionError("grant removed; use an external CapabilityIssuer")

    def resolve(self, *_args, **_kwargs):
        """Removed: plaintext secret resolution is not a public operation."""
        raise PermissionError("plaintext secret resolution is disabled")


__all__ = [
    "CAPABILITY_DOMAIN",
    "CAPABILITY_PURPOSE",
    "DEFAULT_CAPABILITY_TTL_S",
    "MAX_CAPABILITY_TTL_S",
    "MAX_REQUEST_BYTES",
    "MAX_RESPONSE_BYTES",
    "MAX_JSON_STRING_CHARS",
    "SecretScope",
    "TransportOperation",
    "CapabilityToken",
    "CapabilityCheck",
    "CapabilityIssuer",
    "CapabilityVerifier",
    "CapabilityReplayStore",
    "SecretBrokerError",
    "SecretDispatchError",
    "SecretsBroker",
]
