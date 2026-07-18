"""Evidence verification with explicit issuers and verifier-only acceptors.

The canonical module owns no signing secret.  A trusted evidence service receives
an :class:`EvidenceIssuer`; consumers receive only an :class:`EvidenceAcceptor`
containing a fixed issuer allowlist.  Approval and payment proofs use separate
issuer/verifier types and separate trust maps.

Legacy module-level ``verify``/``accept`` helpers remain fail closed: without an
explicit issuer/acceptor they can produce diagnostics, but never an acceptable
attestation.  Claim-selected code is never executed and file/repository checks
are confined to roots fixed when the issuer is constructed.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import shutil
import stat
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Callable, Mapping


EVIDENCE_DOMAIN = b"MAWORLD/EVIDENCE-RESULT/V1\x00"
APPROVAL_DOMAIN = b"MAWORLD/APPROVAL-PROOF/V1\x00"
PAYMENT_DOMAIN = b"MAWORLD/PAYMENT-PROOF/V1\x00"
_MAX_TTL_S = 300
_MAX_FUTURE_SKEW_S = 5
_MAX_FILE_BYTES = 16 * 1024 * 1024
_MAX_CONTAINS_BYTES = 1024 * 1024
_MAX_CONTAINS_NEEDLE_BYTES = 4096
_MAX_GIT_STDOUT_BYTES = 1024 * 1024
_MAX_GIT_STDERR_BYTES = 64 * 1024
_MAX_GIT_METADATA_ENTRIES = 100_000
_GIT_TIMEOUT_S = 5
_FULL_OID_RE = re.compile(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})\Z")
_WINDOWS_REPARSE_POINT = 0x400

SignFn = Callable[[bytes], str]
VerifyFn = Callable[[bytes, str], bool]


def _canonical(value) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode()


def _required(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _digest(value) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _valid_ttl(ttl_s: int) -> int:
    if (
        not isinstance(ttl_s, int)
        or isinstance(ttl_s, bool)
        or not 0 < ttl_s <= _MAX_TTL_S
    ):
        raise ValueError(f"ttl_s must be in 1..{_MAX_TTL_S}")
    return ttl_s


class Truth(str, Enum):
    VERIFIED = "VERIFIED"
    REFUTED = "REFUTED"
    UNKNOWN = "UNKNOWN"


class ClaimKind(str, Enum):
    FILE_CREATED = "file_created"
    CODE_TESTS_PASS = "code_tests_pass"
    COMMIT_MADE = "commit_made"
    WORKFLOW_RECOVERED = "workflow_recovered"
    MEMORY_PROMOTED = "memory_promoted"
    CONTINUITY_PRESERVED = "continuity_preserved"
    PRODUCT_SUCCESS = "product_success"


@dataclass
class Claim:
    kind: ClaimKind
    subject: dict
    asserted_by: str
    claim_id: str = field(default_factory=lambda: "clm-" + uuid.uuid4().hex[:10])

    def canonical(self) -> bytes:
        return _canonical({
            "claim_id": self.claim_id,
            "kind": self.kind.value,
            "subject": self.subject,
            "asserted_by": self.asserted_by,
        })

    def digest(self) -> str:
        return hashlib.sha256(self.canonical()).hexdigest()


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class VerificationResult:
    claim_id: str
    kind: ClaimKind
    truth: Truth
    checks: list
    claim_digest: str = ""
    issuer_id: str = ""
    result_id: str = ""
    issued_at: int = 0
    expires_at: int = 0
    sig: str = ""

    def _payload(self) -> bytes:
        return _canonical({
            "claim_id": self.claim_id,
            "kind": self.kind.value,
            "truth": self.truth.value,
            "claim_digest": self.claim_digest,
            "issuer_id": self.issuer_id,
            "result_id": self.result_id,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "checks": [(c.name, c.passed, c.detail) for c in self.checks],
        })

    def all_passed(self) -> bool:
        return bool(self.checks) and all(
            isinstance(c, Check) and c.passed for c in self.checks
        )


@dataclass
class AcceptanceDecision:
    claim_id: str
    accepted: bool
    reason: str
    verification_truth: Truth


@dataclass
class RegressionFixture:
    fixture_id: str
    claim_id: str
    kind: ClaimKind
    failure_class: str
    expected_behavior: str
    repro: dict


@dataclass(frozen=True)
class ProofToken:
    issuer_id: str
    purpose: str
    subject_digest: str
    token_id: str
    issued_at: int
    expires_at: int
    sig: str = ""

    def _payload(self) -> bytes:
        return _canonical({
            "issuer_id": self.issuer_id,
            "purpose": self.purpose,
            "subject_digest": self.subject_digest,
            "token_id": self.token_id,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        })

    def to_dict(self) -> dict:
        return {
            "issuer_id": self.issuer_id,
            "purpose": self.purpose,
            "subject_digest": self.subject_digest,
            "token_id": self.token_id,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "sig": self.sig,
        }

    @classmethod
    def from_dict(cls, raw: object) -> "ProofToken | None":
        if not isinstance(raw, dict):
            return None
        expected = {
            "issuer_id", "purpose", "subject_digest", "token_id",
            "issued_at", "expires_at", "sig",
        }
        if set(raw) != expected:
            return None
        try:
            token = cls(**raw)
        except (TypeError, ValueError):
            return None
        if (
            not all(isinstance(v, str) and v for v in (
                token.issuer_id, token.purpose, token.subject_digest,
                token.token_id, token.sig,
            ))
            or not isinstance(token.issued_at, int)
            or isinstance(token.issued_at, bool)
            or not isinstance(token.expires_at, int)
            or isinstance(token.expires_at, bool)
        ):
            return None
        return token


class _ProofIssuer:
    purpose: str
    domain: bytes

    def __init__(self, issuer_id: str, sign: SignFn, *, clock=time.time):
        self.issuer_id = _required("issuer_id", issuer_id)
        if not callable(sign):
            raise TypeError("sign must be callable")
        self.__sign = sign
        self._clock = clock

    def _issue(self, subject: dict, *, ttl_s: int, now: int | None) -> dict:
        ttl_s = _valid_ttl(ttl_s)
        issued_at = int(self._clock()) if now is None else int(now)
        unsigned = ProofToken(
            issuer_id=self.issuer_id,
            purpose=self.purpose,
            subject_digest=_digest(subject),
            token_id=uuid.uuid4().hex,
            issued_at=issued_at,
            expires_at=issued_at + ttl_s,
        )
        sig = self.__sign(self.domain + unsigned._payload())
        if not isinstance(sig, str) or not sig:
            raise ValueError("proof signer returned an invalid signature")
        return ProofToken(**{**unsigned.__dict__, "sig": sig}).to_dict()


class ApprovalProofIssuer(_ProofIssuer):
    purpose = "memory_approval"
    domain = APPROVAL_DOMAIN

    def issue(
        self, statement_hash: str, *, ttl_s: int = 60, now: int | None = None
    ) -> dict:
        return self._issue(
            {"statement_hash": _required("statement_hash", statement_hash)},
            ttl_s=ttl_s,
            now=now,
        )


class PaymentProofIssuer(_ProofIssuer):
    purpose = "payment_received"
    domain = PAYMENT_DOMAIN

    def issue(
        self, payment_id: str, amount_cents: int, event_type: str,
        *, tenant_id: str, merchant_account: str, customer_id: str,
        currency: str, provider: str, ttl_s: int = 60,
        now: int | None = None,
    ) -> dict:
        if (
            not isinstance(amount_cents, int)
            or isinstance(amount_cents, bool)
            or amount_cents <= 0
        ):
            raise ValueError("amount_cents must be a positive integer")
        if not isinstance(currency, str) or len(currency.strip()) != 3:
            raise ValueError("currency must be a three-letter code")
        return self._issue({
            "payment_id": _required("payment_id", payment_id),
            "amount_cents": amount_cents,
            "event_type": _required("event_type", event_type),
            "tenant_id": _required("tenant_id", tenant_id),
            "merchant_account": _required("merchant_account", merchant_account),
            "customer_id": _required("customer_id", customer_id),
            "currency": currency.strip().upper(),
            "provider": _required("provider", provider),
        }, ttl_s=ttl_s, now=now)


class _ProofVerifier:
    purpose: str
    domain: bytes

    def __init__(
        self, issuer_verifiers: Mapping[str, VerifyFn], *, clock=time.time,
        max_ttl_s: int = _MAX_TTL_S,
        max_future_skew_s: int = _MAX_FUTURE_SKEW_S,
    ):
        if not issuer_verifiers or any(
            not isinstance(k, str) or not k or not callable(v)
            for k, v in issuer_verifiers.items()
        ):
            raise ValueError("a fixed proof issuer allowlist is required")
        self._verifiers = MappingProxyType(dict(issuer_verifiers))
        self._clock = clock
        self._max_ttl = int(max_ttl_s)
        self._future_skew = int(max_future_skew_s)

    def _verify(self, raw: object, subject: dict) -> bool:
        token = ProofToken.from_dict(raw)
        if token is None or token.purpose != self.purpose:
            return False
        verify = self._verifiers.get(token.issuer_id)
        if verify is None or token.subject_digest != _digest(subject):
            return False
        now = int(self._clock())
        if (
            token.issued_at > now + self._future_skew
            or now >= token.expires_at
            or token.expires_at <= token.issued_at
            or token.expires_at - token.issued_at > self._max_ttl
        ):
            return False
        try:
            return bool(verify(self.domain + token._payload(), token.sig))
        except Exception:
            return False


class ApprovalProofVerifier(_ProofVerifier):
    purpose = "memory_approval"
    domain = APPROVAL_DOMAIN

    def verify(self, raw: object, statement_hash: str) -> bool:
        if not isinstance(statement_hash, str) or not statement_hash:
            return False
        return self._verify(raw, {"statement_hash": statement_hash})


class PaymentProofVerifier(_ProofVerifier):
    purpose = "payment_received"
    domain = PAYMENT_DOMAIN

    def verify(
        self, raw: object, payment_id: str, amount_cents: int, event_type: str,
        *, tenant_id: str, merchant_account: str, customer_id: str,
        currency: str, provider: str,
    ) -> bool:
        if (
            not isinstance(payment_id, str) or not payment_id
            or not isinstance(event_type, str) or not event_type
            or not isinstance(amount_cents, int) or isinstance(amount_cents, bool)
            or amount_cents <= 0
            or not isinstance(tenant_id, str) or not tenant_id
            or not isinstance(merchant_account, str) or not merchant_account
            or not isinstance(customer_id, str) or not customer_id
            or not isinstance(currency, str) or len(currency.strip()) != 3
            or not isinstance(provider, str) or not provider
        ):
            return False
        return self._verify(raw, {
            "payment_id": payment_id,
            "amount_cents": amount_cents,
            "event_type": event_type,
            "tenant_id": tenant_id,
            "merchant_account": merchant_account,
            "customer_id": customer_id,
            "currency": currency.strip().upper(),
            "provider": provider,
        })


# Events that actually prove money received (delayed methods excluded).
PAYMENT_PROVING = {
    "payment_intent.succeeded", "invoice.payment_succeeded",
    "invoice.paid", "charge.succeeded",
}
NON_PROVING = {
    "checkout.session.completed", "customer.subscription.created",
    "customer.subscription.updated", "invoice.created",
}


@dataclass(frozen=True)
class _TrustedRoot:
    path: str
    device: int
    inode: int


@dataclass(frozen=True)
class _FileSnapshot:
    digest: str
    content: bytes
    size: int


@dataclass(frozen=True)
class _BoundedProcess:
    returncode: int
    stdout: bytes
    stderr: bytes
    timed_out: bool = False
    output_overflow: bool = False


@dataclass(frozen=True)
class _GitRuntime:
    executable: str
    device: int
    inode: int
    environment: Mapping[str, str]


def _is_link_or_reparse(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & _WINDOWS_REPARSE_POINT
    )


def _same_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return left.st_dev == right.st_dev and left.st_ino == right.st_ino


def _path_inside(path: str, root: str) -> bool:
    try:
        path_cmp = os.path.normcase(os.path.abspath(path))
        root_cmp = os.path.normcase(os.path.abspath(root))
        return os.path.commonpath((path_cmp, root_cmp)) == root_cmp
    except (OSError, ValueError):
        return False


def _pin_root(raw_root) -> _TrustedRoot:
    root = os.path.realpath(os.path.abspath(os.fspath(raw_root)))
    info = os.lstat(root)
    if _is_link_or_reparse(info) or not stat.S_ISDIR(info.st_mode):
        raise ValueError("file_roots must resolve to canonical directories")
    return _TrustedRoot(root, info.st_dev, info.st_ino)


def _candidate_in_root(path: object, roots: tuple[_TrustedRoot, ...]):
    if (
        not isinstance(path, str)
        or not path
        or "\x00" in path
        or not os.path.isabs(path)
    ):
        return None, None
    try:
        candidate = os.path.abspath(os.path.normpath(path))
    except (OSError, ValueError):
        return None, None
    for root in roots:
        if _path_inside(candidate, root.path):
            return candidate, root
    return candidate, None


def _walk_without_links(
    candidate: str, root: _TrustedRoot, *, final_directory: bool
) -> tuple[bool, str]:
    """Fallback path walk; the opened handle is still authoritative afterwards."""
    try:
        root_info = os.lstat(root.path)
        if (
            _is_link_or_reparse(root_info)
            or not stat.S_ISDIR(root_info.st_mode)
            or root_info.st_dev != root.device
            or root_info.st_ino != root.inode
        ):
            return False, "trusted root identity changed"
        relative = os.path.relpath(candidate, root.path)
        if relative == os.curdir:
            parts = []
        else:
            parts = relative.split(os.sep)
        if any(part in ("", os.curdir, os.pardir) for part in parts):
            return False, "invalid relative path"
        current = root.path
        for index, part in enumerate(parts):
            current = os.path.join(current, part)
            info = os.lstat(current)
            if _is_link_or_reparse(info):
                return False, "symbolic link or reparse point rejected"
            is_final = index == len(parts) - 1
            if not is_final and not stat.S_ISDIR(info.st_mode):
                return False, "non-directory path component"
            if is_final and final_directory != stat.S_ISDIR(info.st_mode):
                return False, "unexpected final path type"
        return True, "canonical path components"
    except (OSError, ValueError):
        return False, "path walk failed"


def _fd_final_path(fd: int) -> str | None:
    if os.name == "nt":
        try:
            import ctypes
            import msvcrt

            handle = msvcrt.get_osfhandle(fd)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            get_path = kernel32.GetFinalPathNameByHandleW
            get_path.argtypes = [
                ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32,
                ctypes.c_uint32,
            ]
            get_path.restype = ctypes.c_uint32
            needed = get_path(handle, None, 0, 0)
            if not needed:
                return None
            buffer = ctypes.create_unicode_buffer(needed + 1)
            written = get_path(handle, buffer, len(buffer), 0)
            if not written or written >= len(buffer):
                return None
            value = buffer.value
            if value.startswith("\\\\?\\UNC\\"):
                value = "\\\\" + value[8:]
            elif value.startswith("\\\\?\\"):
                value = value[4:]
            return os.path.realpath(os.path.abspath(value))
        except (ImportError, OSError, ValueError):
            return None
    for base in ("/proc/self/fd", "/dev/fd"):
        link = os.path.join(base, str(fd))
        try:
            if os.path.lexists(link):
                return os.path.realpath(os.readlink(link))
        except OSError:
            continue
    return None


def _open_trusted_file(
    path: object, roots: tuple[_TrustedRoot, ...]
) -> tuple[int | None, str]:
    candidate, root = _candidate_in_root(path, roots)
    if candidate is None or root is None or candidate == root.path:
        return None, "path outside an explicit trusted root"

    supports_dirfd = (
        os.name != "nt"
        and hasattr(os, "O_NOFOLLOW")
        and os.open in getattr(os, "supports_dir_fd", set())
        and os.stat in getattr(os, "supports_dir_fd", set())
        and os.stat in getattr(os, "supports_follow_symlinks", set())
    )
    if supports_dirfd:
        directory_fd = None
        file_fd = None
        try:
            directory_flags = (
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_CLOEXEC", 0)
                | os.O_NOFOLLOW
            )
            directory_fd = os.open(root.path, directory_flags)
            root_info = os.fstat(directory_fd)
            if (
                not stat.S_ISDIR(root_info.st_mode)
                or root_info.st_dev != root.device
                or root_info.st_ino != root.inode
            ):
                return None, "trusted root identity changed"
            parts = os.path.relpath(candidate, root.path).split(os.sep)
            if any(part in ("", os.curdir, os.pardir) for part in parts):
                return None, "invalid relative path"
            for part in parts[:-1]:
                next_fd = os.open(part, directory_flags, dir_fd=directory_fd)
                os.close(directory_fd)
                directory_fd = next_fd
            file_flags = (
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NONBLOCK", 0)
                | os.O_NOFOLLOW
            )
            file_fd = os.open(parts[-1], file_flags, dir_fd=directory_fd)
            file_info = os.fstat(file_fd)
            leaf_info = os.stat(
                parts[-1], dir_fd=directory_fd, follow_symlinks=False
            )
            final_path = _fd_final_path(file_fd)
            if (
                not stat.S_ISREG(file_info.st_mode)
                or _is_link_or_reparse(leaf_info)
                or not _same_identity(file_info, leaf_info)
                or final_path is None
                or not _path_inside(final_path, root.path)
            ):
                os.close(file_fd)
                file_fd = None
                return None, "opened handle is not a rooted regular file"
            return file_fd, "descriptor-pinned no-follow file"
        except (OSError, ValueError):
            if file_fd is not None:
                os.close(file_fd)
            return None, "secure descriptor open failed"
        finally:
            if directory_fd is not None:
                os.close(directory_fd)

    before_ok, before_detail = _walk_without_links(
        candidate, root, final_directory=False
    )
    if not before_ok:
        return None, before_detail
    file_fd = None
    try:
        flags = (
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOINHERIT", 0)
        )
        file_fd = os.open(candidate, flags)
        file_info = os.fstat(file_fd)
        final_path = _fd_final_path(file_fd)
        after_ok, after_detail = _walk_without_links(
            candidate, root, final_directory=False
        )
        current_info = os.lstat(candidate) if after_ok else None
        if (
            not stat.S_ISREG(file_info.st_mode)
            or final_path is None
            or not _path_inside(final_path, root.path)
            or not after_ok
            or current_info is None
            or not _same_identity(file_info, current_info)
        ):
            os.close(file_fd)
            file_fd = None
            return None, after_detail if not after_ok else "handle/path identity mismatch"
        return file_fd, "descriptor-pinned rooted file"
    except (OSError, ValueError):
        if file_fd is not None:
            os.close(file_fd)
        return None, "secure descriptor open failed"


def _snapshot_trusted_file(
    path: object, roots: tuple[_TrustedRoot, ...], *, capture_content: bool
) -> tuple[_FileSnapshot | None, str]:
    fd, detail = _open_trusted_file(path, roots)
    if fd is None:
        return None, detail
    try:
        before = os.fstat(fd)
        content_limit = _MAX_CONTAINS_BYTES if capture_content else _MAX_FILE_BYTES
        if before.st_size < 0 or before.st_size > min(_MAX_FILE_BYTES, content_limit):
            return None, "file exceeds the evidence size limit"
        digest = hashlib.sha256()
        chunks = []
        total = 0
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            total += len(chunk)
            if total > _MAX_FILE_BYTES or (capture_content and total > content_limit):
                return None, "file grew beyond the evidence size limit"
            digest.update(chunk)
            if capture_content:
                chunks.append(chunk)
        after = os.fstat(fd)
        stable = (
            _same_identity(before, after)
            and before.st_size == after.st_size == total
            and getattr(before, "st_mtime_ns", None)
            == getattr(after, "st_mtime_ns", None)
            and getattr(before, "st_ctime_ns", None)
            == getattr(after, "st_ctime_ns", None)
        )
        if not stable:
            return None, "file changed while evidence was captured"
        return _FileSnapshot(
            digest.hexdigest(), b"".join(chunks), total
        ), detail
    except OSError:
        return None, "descriptor read failed"
    finally:
        os.close(fd)


def _fixed_git_environment() -> Mapping[str, str]:
    environment = {
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_COUNT": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_PROTOCOL_FROM_USER": "0",
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_PAGER": "cat",
        "LC_ALL": "C",
        "LANG": "C",
    }
    # CreateProcess needs these on Windows; no Git-controlled variable is inherited.
    for name in ("SystemRoot", "SYSTEMROOT", "WINDIR"):
        value = os.environ.get(name)
        if value:
            environment[name] = value
    return MappingProxyType(environment)


def _pin_git_runtime(executable: object = None) -> _GitRuntime | None:
    try:
        located = (
            shutil.which("git") if executable is None else os.fspath(executable)
        )
        if not located:
            return None
        fixed = os.path.realpath(os.path.abspath(located))
        info = os.lstat(fixed)
        if _is_link_or_reparse(info) or not stat.S_ISREG(info.st_mode):
            return None
        return _GitRuntime(
            fixed, info.st_dev, info.st_ino, _fixed_git_environment()
        )
    except (OSError, TypeError, ValueError):
        return None


def _run_bounded(
    argv: list[str], *, environment: Mapping[str, str], cwd: str,
    timeout_s: int = _GIT_TIMEOUT_S,
    stdout_limit: int = _MAX_GIT_STDOUT_BYTES,
    stderr_limit: int = _MAX_GIT_STDERR_BYTES,
) -> _BoundedProcess:
    try:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            close_fds=True,
        )
    except (OSError, ValueError):
        return _BoundedProcess(-1, b"", b"process launch failed")

    buffers = {"stdout": [], "stderr": []}
    overflow = threading.Event()

    def drain(name: str, pipe, limit: int):
        size = 0
        try:
            while True:
                chunk = pipe.read(65536)
                if not chunk:
                    break
                remaining = max(0, limit - size)
                if remaining:
                    buffers[name].append(chunk[:remaining])
                    size += min(len(chunk), remaining)
                if len(chunk) > remaining:
                    overflow.set()
                    try:
                        process.kill()
                    except OSError:
                        pass
                    break
        finally:
            try:
                pipe.close()
            except OSError:
                pass

    stdout_thread = threading.Thread(
        target=drain,
        args=("stdout", process.stdout, stdout_limit),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=drain,
        args=("stderr", process.stderr, stderr_limit),
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()
    timed_out = False
    try:
        process.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            process.kill()
        except OSError:
            pass
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
    stdout_thread.join(timeout=1)
    stderr_thread.join(timeout=1)
    if stdout_thread.is_alive() or stderr_thread.is_alive():
        overflow.set()
    return _BoundedProcess(
        process.returncode if process.returncode is not None else -1,
        b"".join(buffers["stdout"]),
        b"".join(buffers["stderr"]),
        timed_out,
        overflow.is_set(),
    )


def _git_metadata_safe(git_dir: str) -> tuple[bool, str]:
    forbidden = (
        "commondir",
        "shallow",
        os.path.join("objects", "info", "alternates"),
        os.path.join("objects", "info", "http-alternates"),
        os.path.join("info", "grafts"),
    )
    try:
        root_info = os.lstat(git_dir)
        if _is_link_or_reparse(root_info) or not stat.S_ISDIR(root_info.st_mode):
            return False, ".git must be a direct canonical directory"
        for relative in forbidden:
            if os.path.lexists(os.path.join(git_dir, relative)):
                return False, f"forbidden Git indirection: {relative}"
        objects = os.path.join(git_dir, "objects")
        objects_info = os.lstat(objects)
        if _is_link_or_reparse(objects_info) or not stat.S_ISDIR(objects_info.st_mode):
            return False, "Git object directory is not direct"
        pending = [git_dir]
        count = 0
        while pending:
            directory = pending.pop()
            with os.scandir(directory) as entries:
                for entry in entries:
                    count += 1
                    if count > _MAX_GIT_METADATA_ENTRIES:
                        return False, "Git metadata entry limit exceeded"
                    info = entry.stat(follow_symlinks=False)
                    if _is_link_or_reparse(info):
                        return False, "Git metadata contains a link/reparse point"
                    if stat.S_ISDIR(info.st_mode):
                        pending.append(entry.path)
                    elif not stat.S_ISREG(info.st_mode):
                        return False, "Git metadata contains a special file"
        git_root = _pin_root(git_dir)
        for config_name in ("config", "config.worktree"):
            config_path = os.path.join(git_dir, config_name)
            if not os.path.lexists(config_path):
                continue
            snapshot, _detail = _snapshot_trusted_file(
                config_path, (git_root,), capture_content=True
            )
            if snapshot is None or b"\x00" in snapshot.content:
                return False, "Git config is not a bounded direct file"
            try:
                config_text = snapshot.content.decode("utf-8", "strict")
            except UnicodeError:
                return False, "Git config is not canonical UTF-8"
            if re.search(r"(?im)^\s*\[\s*include(?:if)?(?:\s|\])", config_text):
                return False, "Git config include indirection is forbidden"
        return True, "direct .git directory without alternates or links"
    except (OSError, ValueError):
        return False, "Git metadata inspection failed"


def _canonical_git_repo(
    repo: object, roots: tuple[_TrustedRoot, ...]
) -> tuple[str | None, str | None, str]:
    candidate, root = _candidate_in_root(repo, roots)
    if candidate is None or root is None:
        return None, None, "repository outside an explicit trusted root"
    path_ok, detail = _walk_without_links(
        candidate, root, final_directory=True
    )
    if not path_ok:
        return None, None, detail
    try:
        if os.path.normcase(os.path.realpath(candidate)) != os.path.normcase(candidate):
            return None, None, "repository path is not canonical"
        git_dir = os.path.join(candidate, ".git")
        git_info = os.lstat(git_dir)
        if (
            _is_link_or_reparse(git_info)
            or not stat.S_ISDIR(git_info.st_mode)
            or os.path.normcase(os.path.realpath(git_dir))
            != os.path.normcase(git_dir)
            or not _path_inside(git_dir, root.path)
        ):
            return None, None, ".git indirection is forbidden"
    except OSError:
        return None, None, "direct .git directory missing"
    metadata_ok, metadata_detail = _git_metadata_safe(git_dir)
    if not metadata_ok:
        return None, None, metadata_detail
    return candidate, git_dir, metadata_detail


def _git_call(
    runtime: _GitRuntime, repo: str, git_dir: str, arguments: list[str]
) -> _BoundedProcess:
    try:
        executable_info = os.lstat(runtime.executable)
        if (
            _is_link_or_reparse(executable_info)
            or not stat.S_ISREG(executable_info.st_mode)
            or executable_info.st_dev != runtime.device
            or executable_info.st_ino != runtime.inode
        ):
            return _BoundedProcess(-1, b"", b"pinned Git executable changed")
    except OSError:
        return _BoundedProcess(-1, b"", b"pinned Git executable unavailable")
    argv = [
        runtime.executable,
        "--no-pager",
        f"--git-dir={git_dir}",
        f"--work-tree={repo}",
        "-c", f"safe.directory={repo}",
        "-c", "core.hooksPath=",
        "-c", "core.fsmonitor=false",
        "-c", "core.pager=cat",
        "-c", "core.attributesFile=",
        "-c", "pager.show=false",
        "-c", "diff.external=",
        "-c", "protocol.file.allow=never",
        *arguments,
    ]
    return _run_bounded(
        argv, environment=runtime.environment, cwd=repo,
        stdout_limit=_MAX_GIT_STDOUT_BYTES,
        stderr_limit=_MAX_GIT_STDERR_BYTES,
    )


def _process_succeeded(result: _BoundedProcess) -> bool:
    return (
        result.returncode == 0
        and not result.timed_out
        and not result.output_overflow
    )


def _bounded_utf8(value: object, limit: int) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return len(value.encode("utf-8")) <= limit
    except UnicodeError:
        return False


def _canonical_expected_paths(raw: object) -> set[bytes] | None:
    if not isinstance(raw, list) or len(raw) > 4096:
        return None
    encoded = set()
    for item in raw:
        if (
            not isinstance(item, str)
            or not item
            or "\x00" in item
            or "\\" in item
            or item.startswith("/")
            or any(part in ("", ".", "..") for part in item.split("/"))
        ):
            return None
        try:
            encoded.add(item.encode("utf-8"))
        except UnicodeError:
            return None
    return encoded if len(encoded) == len(raw) else None


def _evaluate(
    claim: Claim, *, registry=None, file_roots: tuple[_TrustedRoot, ...] = (),
    approval_verifier: ApprovalProofVerifier | None = None,
    payment_verifier: PaymentProofVerifier | None = None,
    git_runtime: _GitRuntime | None = None,
) -> list[Check]:
    kind = claim.kind
    subject = claim.subject if isinstance(claim.subject, dict) else {}
    checks: list[Check] = []

    if kind == ClaimKind.FILE_CREATED:
        path = subject.get("path", "")
        _candidate, trusted_root = _candidate_in_root(path, file_roots)
        in_scope = trusted_root is not None
        checks.append(Check("path_in_trusted_root", in_scope, "explicit issuer root"))
        expected_hash = subject.get("sha256")
        expected_contains = subject.get("contains")
        expectation_valid = (
            isinstance(expected_hash, str)
            and bool(re.fullmatch(r"[0-9a-fA-F]{64}", expected_hash))
            and "contains" not in subject
        ) or (
            isinstance(expected_contains, str)
            and "sha256" not in subject
            and _bounded_utf8(expected_contains, _MAX_CONTAINS_NEEDLE_BYTES)
        )
        checks.append(Check(
            "file_expectation_valid", expectation_valid,
            "exactly one bounded hash/contains expectation required",
        ))
        snapshot, snapshot_detail = (None, "invalid or out-of-scope claim")
        if in_scope and expectation_valid:
            snapshot, snapshot_detail = _snapshot_trusted_file(
                path, file_roots, capture_content=isinstance(expected_contains, str)
            )
        checks.append(Check(
            "file_exists", snapshot is not None,
            snapshot_detail if in_scope else "out of scope",
        ))
        if isinstance(expected_hash, str):
            matches = bool(
                snapshot
                and hmac.compare_digest(snapshot.digest, expected_hash.lower())
            )
            checks.append(Check("hash_matches", matches, "descriptor snapshot"))
        elif isinstance(expected_contains, str):
            try:
                matches = bool(
                    snapshot
                    and expected_contains in snapshot.content.decode("utf-8", "replace")
                )
            except (UnicodeError, AttributeError):
                matches = False
            checks.append(Check("content_matches", matches, "descriptor snapshot"))
        else:
            checks.append(Check("hash_matches", False, "no valid expectation"))

    elif kind == ClaimKind.CODE_TESTS_PASS:
        checks.append(Check(
            "trusted_test_attestation", False,
            "host execution disabled; signed CI-runner attestation required",
        ))

    elif kind == ClaimKind.COMMIT_MADE:
        repo = subject.get("repo", "")
        sha = subject.get("sha", "")
        _candidate, trusted_root = _candidate_in_root(repo, file_roots)
        in_scope = trusted_root is not None
        checks.append(Check("repo_in_trusted_root", in_scope, "explicit issuer root"))
        canonical_repo, git_dir, layout_detail = _canonical_git_repo(
            repo, file_roots
        ) if in_scope else (None, None, "repository out of scope")
        layout_safe = canonical_repo is not None and git_dir is not None
        checks.append(Check("git_repository_safe", layout_safe, layout_detail))
        oid_valid = isinstance(sha, str) and bool(_FULL_OID_RE.fullmatch(sha))
        checks.append(Check(
            "commit_id_is_full_oid", oid_valid,
            "mutable refs and abbreviated object ids are forbidden",
        ))
        exists = False
        pinned_oid = ""
        if layout_safe and oid_valid and git_runtime is not None:
            revision = _git_call(
                git_runtime, canonical_repo, git_dir,
                ["rev-parse", "--verify", "--end-of-options", f"{sha}^{{commit}}"],
            )
            if _process_succeeded(revision):
                try:
                    candidate_oid = revision.stdout.decode("ascii", "strict").strip()
                except UnicodeError:
                    candidate_oid = ""
                if (
                    _FULL_OID_RE.fullmatch(candidate_oid)
                    and hmac.compare_digest(candidate_oid.lower(), sha.lower())
                ):
                    pinned_oid = candidate_oid.lower()
                    object_type = _git_call(
                        git_runtime, canonical_repo, git_dir,
                        ["cat-file", "-t", pinned_oid],
                    )
                    exists = (
                        _process_succeeded(object_type)
                        and object_type.stdout == b"commit\n"
                    )
        checks.append(Check(
            "commit_exists", exists,
            pinned_oid[:12] if pinned_oid else "exact commit lookup failed",
        ))
        expected_paths = subject.get("expected_paths")
        if exists and isinstance(expected_paths, list):
            expected = _canonical_expected_paths(expected_paths)
            expected_valid = expected is not None
            diff = _git_call(
                git_runtime, canonical_repo, git_dir,
                [
                    "diff-tree", "--root", "--no-commit-id", "--name-only",
                    "--no-renames", "--no-ext-diff", "--no-textconv",
                    "-r", "-z", pinned_oid,
                ],
            )
            touched = {
                item for item in diff.stdout.split(b"\x00") if item
            } if _process_succeeded(diff) else set()
            checks.append(Check(
                "expected_paths_in_diff",
                expected_valid
                and _process_succeeded(diff)
                and expected.issubset(touched),
                "bounded exact-path diff",
            ))
        elif expected_paths is not None:
            checks.append(Check(
                "expected_paths_in_diff", False,
                "expected_paths must be a bounded list and commit must exist",
            ))
        stable = bool(git_dir and _git_metadata_safe(git_dir)[0])
        checks.append(Check(
            "git_repository_stable", stable,
            "metadata rechecked after exact object queries",
        ))

    elif kind == ClaimKind.WORKFLOW_RECOVERED:
        idem_key = subject.get("idem_key")
        if registry is None or not isinstance(idem_key, str) or not idem_key:
            checks.append(Check(
                "effect_fired_exactly_once", False, "no trusted registry/idem to re-derive"
            ))
        else:
            try:
                count = registry.fired_count(idem_key)
                checks.append(Check(
                    "effect_fired_exactly_once", count == 1,
                    f"registry fired_count={count}",
                ))
            except Exception as exc:
                checks.append(Check(
                    "effect_fired_exactly_once", False,
                    f"registry error={type(exc).__name__}",
                ))

    elif kind == ClaimKind.MEMORY_PROMOTED:
        state = subject.get("promotion_state")
        statement_hash = subject.get("statement_hash", "")
        checks.append(Check(
            "promotion_state_active", state in ("APPROVED", "ACTIVE"), f"state={state}"
        ))
        valid = bool(
            approval_verifier
            and approval_verifier.verify(subject.get("approval_token"), statement_hash)
        )
        checks.append(Check(
            "approval_token_valid", valid,
            "separate approval issuer over exact statement",
        ))

    elif kind == ClaimKind.CONTINUITY_PRESERVED:
        checks.append(Check(
            "trusted_continuity_attestation", False,
            "claim-supplied boolean is not evidence",
        ))

    elif kind == ClaimKind.PRODUCT_SUCCESS:
        event_type = subject.get("event_type")
        payment_id = subject.get("payment_id", "")
        raw_amount = subject.get("amount_cents", 0)
        amount = raw_amount if isinstance(raw_amount, int) and not isinstance(raw_amount, bool) else 0
        if event_type in NON_PROVING:
            checks.append(Check(
                "payment_proven", False,
                f"'{event_type}' does not prove money received",
            ))
        elif event_type in PAYMENT_PROVING and payment_verifier and payment_verifier.verify(
            subject.get("payment_token"), payment_id, amount, event_type,
            tenant_id=subject.get("tenant_id", ""),
            merchant_account=subject.get("merchant_account", ""),
            customer_id=subject.get("customer_id", ""),
            currency=subject.get("currency", ""),
            provider=subject.get("provider", ""),
        ):
            checks.append(Check(
                "payment_proven", True, f"{event_type} {amount}c externally signed"
            ))
        else:
            checks.append(Check(
                "payment_proven", False, f"weak, expired, untrusted, or unsigned '{event_type}'"
            ))

    else:
        checks.append(Check("unknown_kind", False, str(kind)))

    return checks


class EvidenceIssuer:
    """Evidence-service signer with dependencies fixed at construction."""

    def __init__(
        self, issuer_id: str, sign: SignFn, *, registry=None,
        file_roots=(), approval_verifier: ApprovalProofVerifier | None = None,
        payment_verifier: PaymentProofVerifier | None = None, clock=time.time,
        git_executable=None,
    ):
        self.issuer_id = _required("issuer_id", issuer_id)
        if not callable(sign):
            raise TypeError("sign must be callable")
        if approval_verifier is not None and not isinstance(
            approval_verifier, ApprovalProofVerifier
        ):
            raise TypeError("approval_verifier must be ApprovalProofVerifier")
        if payment_verifier is not None and not isinstance(
            payment_verifier, PaymentProofVerifier
        ):
            raise TypeError("payment_verifier must be PaymentProofVerifier")
        self.__sign = sign
        self._registry = registry
        pinned_roots = tuple(_pin_root(root) for root in file_roots)
        if len({os.path.normcase(root.path) for root in pinned_roots}) != len(pinned_roots):
            raise ValueError("file_roots must not contain duplicates")
        self._roots = pinned_roots
        self._approval_verifier = approval_verifier
        self._payment_verifier = payment_verifier
        self._git_runtime = _pin_git_runtime(git_executable)
        self._clock = clock

    def verify(
        self, claim: Claim, *, ttl_s: int = 60, now: int | None = None
    ) -> VerificationResult:
        if not isinstance(claim, Claim):
            raise TypeError("claim must be Claim")
        ttl_s = _valid_ttl(ttl_s)
        issued_at = int(self._clock()) if now is None else int(now)
        checks = _evaluate(
            claim, registry=self._registry, file_roots=self._roots,
            approval_verifier=self._approval_verifier,
            payment_verifier=self._payment_verifier,
            git_runtime=self._git_runtime,
        )
        truth = Truth.VERIFIED if checks and all(c.passed for c in checks) else Truth.REFUTED
        unsigned = VerificationResult(
            claim_id=claim.claim_id,
            kind=claim.kind,
            truth=truth,
            checks=checks,
            claim_digest=claim.digest(),
            issuer_id=self.issuer_id,
            result_id=uuid.uuid4().hex,
            issued_at=issued_at,
            expires_at=issued_at + ttl_s,
        )
        sig = self.__sign(EVIDENCE_DOMAIN + unsigned._payload())
        if not isinstance(sig, str) or not sig:
            raise ValueError("evidence signer returned an invalid signature")
        unsigned.sig = sig
        return unsigned


class EvidenceAcceptor:
    """Verifier-only evidence trust boundary."""

    def __init__(
        self, issuer_verifiers: Mapping[str, VerifyFn], *, clock=time.time,
        max_ttl_s: int = _MAX_TTL_S,
        max_future_skew_s: int = _MAX_FUTURE_SKEW_S,
    ):
        if not issuer_verifiers or any(
            not isinstance(k, str) or not k or not callable(v)
            for k, v in issuer_verifiers.items()
        ):
            raise ValueError("a fixed evidence issuer allowlist is required")
        self._verifiers = MappingProxyType(dict(issuer_verifiers))
        self._clock = clock
        self._max_ttl = int(max_ttl_s)
        self._future_skew = int(max_future_skew_s)

    @staticmethod
    def _decision(claim: Claim, accepted: bool, reason: str, truth=Truth.UNKNOWN):
        return AcceptanceDecision(claim.claim_id, accepted, reason, truth)

    def accept(self, claim: Claim, result: VerificationResult) -> AcceptanceDecision:
        if not isinstance(claim, Claim) or not isinstance(result, VerificationResult):
            raise TypeError("claim and result must use canonical evidence types")
        verify_signature = self._verifiers.get(result.issuer_id)
        if verify_signature is None:
            return self._decision(claim, False, "evidence issuer is not trusted", result.truth)
        try:
            signature_ok = bool(result.sig) and bool(verify_signature(
                EVIDENCE_DOMAIN + result._payload(), result.sig
            ))
        except Exception:
            signature_ok = False
        if not signature_ok:
            return self._decision(
                claim, False, "verification result signature invalid or tampered", result.truth
            )
        now = int(self._clock())
        if (
            result.issued_at > now + self._future_skew
            or now >= result.expires_at
            or result.expires_at <= result.issued_at
            or result.expires_at - result.issued_at > self._max_ttl
        ):
            return self._decision(claim, False, "verification result expired or invalid lifetime", result.truth)
        if result.claim_id != claim.claim_id:
            return self._decision(claim, False, "claim id mismatch", result.truth)
        if result.kind != claim.kind:
            return self._decision(claim, False, "claim kind mismatch", result.truth)
        try:
            digest_ok = bool(result.claim_digest) and hmac.compare_digest(
                result.claim_digest, claim.digest()
            )
        except (TypeError, ValueError):
            digest_ok = False
        if not digest_ok:
            return self._decision(
                claim, False, "verification result bound to another claim", result.truth
            )
        if result.truth != Truth.VERIFIED or not result.all_passed():
            failed = [
                c.name for c in result.checks
                if isinstance(c, Check) and not c.passed
            ]
            return self._decision(
                claim, False, f"not verified; failed={failed}", result.truth
            )
        return self._decision(
            claim, True, "verified by trusted external evidence issuer", result.truth
        )


def verify(
    claim: Claim, registry=None, *, issuer: EvidenceIssuer | None = None
) -> VerificationResult:
    """Compatibility entry point; unsigned diagnostics are never acceptable."""
    if issuer is not None:
        if not isinstance(issuer, EvidenceIssuer):
            raise TypeError("issuer must be EvidenceIssuer")
        if registry is not None:
            raise ValueError("registry must be fixed on EvidenceIssuer")
        return issuer.verify(claim)
    checks = _evaluate(claim, registry=registry)
    truth = Truth.VERIFIED if checks and all(c.passed for c in checks) else Truth.REFUTED
    return VerificationResult(
        claim.claim_id, claim.kind, truth, checks,
        claim_digest=claim.digest(), issuer_id="legacy-untrusted",
    )


def accept(
    claim: Claim, result: VerificationResult, *, acceptor: EvidenceAcceptor | None = None
) -> AcceptanceDecision:
    """Compatibility entry point; an explicit verifier-only acceptor is mandatory."""
    if acceptor is None:
        truth = result.truth if isinstance(result, VerificationResult) else Truth.UNKNOWN
        return AcceptanceDecision(
            claim.claim_id, False, "explicit EvidenceAcceptor required", truth
        )
    if not isinstance(acceptor, EvidenceAcceptor):
        raise TypeError("acceptor must be EvidenceAcceptor")
    return acceptor.accept(claim, result)


def sign_approval(*_args, **_kwargs):
    raise RuntimeError("removed: use an explicit ApprovalProofIssuer outside the verifier")


def sign_payment(*_args, **_kwargs):
    raise RuntimeError("removed: use an explicit PaymentProofIssuer outside the verifier")


def fixture_from_failure(claim: Claim, result: VerificationResult) -> RegressionFixture:
    failed = [c for c in result.checks if isinstance(c, Check) and not c.passed]
    return RegressionFixture(
        "fix-" + uuid.uuid4().hex[:10], claim.claim_id, claim.kind,
        (failed[0].name if failed else "unknown") + "_failed",
        "all requirement checks must pass",
        {"subject": claim.subject, "failed": [asdict(c) for c in failed]},
    )


def pilot_gate(
    pilot_ids,
    payment_attestations,
    *,
    tenant_id: str,
    merchant_account: str,
    currency: str,
    acceptor: EvidenceAcceptor,
):
    """Scale only on unique pilots with accepted, scoped payment attestations."""
    if not isinstance(acceptor, EvidenceAcceptor):
        raise TypeError("explicit EvidenceAcceptor required")
    pilots = {
        pilot_id for pilot_id in pilot_ids
        if isinstance(pilot_id, str) and pilot_id
    }
    paying_customers = set()
    payment_ids = set()
    for item in payment_attestations:
        if not isinstance(item, tuple) or len(item) != 2:
            continue
        claim, result = item
        if (
            not isinstance(claim, Claim)
            or claim.kind != ClaimKind.PRODUCT_SUCCESS
            or not acceptor.accept(claim, result).accepted
        ):
            continue
        subject = claim.subject
        payment_id = subject.get("payment_id")
        customer_id = subject.get("customer_id")
        scoped = (
            subject.get("tenant_id") == tenant_id
            and subject.get("merchant_account") == merchant_account
            and isinstance(subject.get("currency"), str)
            and subject["currency"].upper() == currency.upper()
        )
        if (
            scoped
            and customer_id in pilots
            and isinstance(payment_id, str) and payment_id
            and payment_id not in payment_ids
            and customer_id not in paying_customers
        ):
            payment_ids.add(payment_id)
            paying_customers.add(customer_id)
    return {
        "pilots": len(pilots),
        "paying": len(paying_customers),
        "decision": (
            "SCALE" if len(pilots) >= 5 and len(paying_customers) >= 3 else "HOLD"
        ),
    }
