"""Fail-closed Tier-2 runner for untrusted Python.

The runner is deliberately composition-only: production code must provide an
absolute gVisor ``runsc`` path, its expected SHA-256 digest, and an absolute
rootfs path backed by a read-only Linux mount.  The module never discovers an
executable through ``PATH`` and has no direct-Python or bwrap fallback.

An exit code is not an isolation attestation.  ``RunResult.isolated`` and
``RunResult.egress_denied`` always remain false in this local component.  A
separate signed deployment-attestation verifier is required before production
may claim either property; caller booleans are deliberately not accepted.
"""
from __future__ import annotations

import hashlib
import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import uuid
from dataclasses import dataclass
from typing import BinaryIO, Mapping, Sequence


DEFAULT_OUTPUT_BYTES = 64 * 1024
MAX_OUTPUT_BYTES = 1024 * 1024
MAX_CODE_BYTES = 256 * 1024
MAX_TIMEOUT_SECONDS = 300.0
MAX_MEMORY_BYTES = 512 * 1024 * 1024
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_PROCESSES = 256
MAX_CONCURRENT_RUNS = 4

# This runner does not consume or verify deployment attestations.  A separate
# trust boundary must verify a signed statement containing *all* of these
# claims before treating any result as security-accepted.  Keeping the list
# here makes the production contract explicit without introducing caller-
# asserted booleans or a caller-selected verification key.
REQUIRED_DEPLOYMENT_ATTESTATION_CLAIMS = (
    "backend_sha256",
    "backend_file_identity",
    "rootfs_image_digest",
    "rootfs_mount_identity",
    "oci_policy_digest",
    "host_identity",
    "issued_at",
    "expires_at",
    "nonce",
)

_RUN_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENT_RUNS)


class NoSandboxAvailable(RuntimeError):
    """A supported, validated isolation backend is unavailable."""


class UnsafeModeDisabled(NoSandboxAvailable):
    """A caller requested a removed discovery or fallback mode."""


class BackendValidationError(NoSandboxAvailable):
    """The pinned backend or rootfs does not match its composition policy."""


class Tier2CapacityExceeded(NoSandboxAvailable):
    """The bounded executor has no free slot; nothing was executed."""


def BackendAcceptance(*_args: object, **_kwargs: object):
    """Removed caller-asserted acceptance object."""
    raise TypeError(
        "caller-asserted isolation booleans are disabled; verify a signed "
        "deployment attestation outside Tier2Runner"
    )


@dataclass(frozen=True)
class RunResult:
    ok: bool
    mechanism: str
    stdout: str
    stderr: str
    exit_code: int
    egress_denied: bool
    isolated: bool
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    timed_out: bool = False


@dataclass(frozen=True)
class _ProcessOutcome:
    stdout: str
    stderr: str
    exit_code: int
    stdout_truncated: bool
    stderr_truncated: bool
    timed_out: bool


@dataclass(frozen=True)
class _BackendIdentity:
    device: int
    inode: int
    size: int
    mtime_ns: int
    sha256: str


@dataclass(frozen=True)
class _RootfsIdentity:
    device: int
    inode: int
    mode: int
    uid: int
    gid: int
    mount_id: int
    read_only_mount: bool


def _host_supports_tier2() -> bool:
    return os.name == "posix" and sys.platform.startswith("linux")


def _normalize_sha256(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("expected_sha256 must be a string")
    digest = value.strip().lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError("expected_sha256 must be exactly 64 hexadecimal characters")
    return digest


def _require_absolute_unaliased(path: str, label: str) -> str:
    if not isinstance(path, str) or not path:
        raise TypeError(f"{label} must be a non-empty string")
    if not os.path.isabs(path):
        raise BackendValidationError(f"{label} must be an absolute path")
    absolute = os.path.abspath(path)
    real = os.path.realpath(path)
    if os.path.normcase(absolute) != os.path.normcase(real):
        raise BackendValidationError(f"{label} must not contain symlinks or aliases")
    return absolute


def _sha256_fd(fd: int) -> str:
    digest = hashlib.sha256()
    with os.fdopen(os.dup(fd), "rb", closefd=True) as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _validate_protected_directory_fd(fd: int, label: str) -> os.stat_result:
    info = os.fstat(fd)
    if not stat.S_ISDIR(info.st_mode):
        raise BackendValidationError(f"{label} must be a real directory")
    if info.st_uid != 0:
        raise BackendValidationError(f"{label} must be owned by root (uid 0)")
    if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise BackendValidationError(f"{label} must not be group/world writable")
    return info


def _open_protected_parent(path: str, label: str) -> tuple[int, str]:
    """Walk an absolute Linux path through pinned, no-follow directory FDs.

    Checking string paths and then opening the target would leave a rename or
    symlink race.  Walking from ``/`` with ``openat`` semantics pins every
    parent while also requiring an unprivileged process to be unable to replace
    any path component.
    """
    absolute = _require_absolute_unaliased(path, label)
    if not _host_supports_tier2():
        raise NoSandboxAvailable("protected descriptor walk requires Linux")
    components = [part for part in absolute.split(os.sep) if part]
    if not components:
        raise BackendValidationError(f"{label} cannot be the host root")
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    current = os.open(os.sep, directory_flags)
    try:
        _validate_protected_directory_fd(current, f"{label} parent /")
        for index, component in enumerate(components[:-1], start=1):
            try:
                next_fd = os.open(component, directory_flags, dir_fd=current)
            except OSError as error:
                raise BackendValidationError(
                    f"{label} parent component {index} is unavailable: {error}"
                ) from error
            try:
                _validate_protected_directory_fd(
                    next_fd, f"{label} parent component {index}"
                )
            except Exception:
                os.close(next_fd)
                raise
            os.close(current)
            current = next_fd
        return current, components[-1]
    except Exception:
        os.close(current)
        raise


def _backend_identity_from_fd(fd: int, expected_sha256: str) -> _BackendIdentity:
    expected = _normalize_sha256(expected_sha256)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode):
        raise BackendValidationError("backend must be a regular file")
    if os.name == "posix":
        if info.st_uid != 0:
            raise BackendValidationError("Linux backend must be owned by root (uid 0)")
        if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise BackendValidationError("Linux backend must not be group/world writable")
        if not info.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
            raise BackendValidationError("Linux backend must have an executable mode bit")
    actual = _sha256_fd(fd)
    if actual != expected:
        raise BackendValidationError("backend SHA-256 does not match pinned composition")
    return _BackendIdentity(
        device=int(info.st_dev),
        inode=int(info.st_ino),
        size=int(info.st_size),
        mtime_ns=int(info.st_mtime_ns),
        sha256=actual,
    )


def _open_validated_backend(
    path: str,
    expected_sha256: str,
    expected_identity: _BackendIdentity | None = None,
) -> tuple[int, _BackendIdentity]:
    parent_fd, name = _open_protected_parent(path, "backend_path")
    try:
        try:
            fd = os.open(
                name,
                os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
                dir_fd=parent_fd,
            )
        except OSError as error:
            raise BackendValidationError(f"backend is unavailable: {error}") from error
    finally:
        os.close(parent_fd)
    try:
        identity = _backend_identity_from_fd(fd, expected_sha256)
        if expected_identity is not None and identity != expected_identity:
            raise BackendValidationError("backend identity changed after composition")
        return fd, identity
    except Exception:
        os.close(fd)
        raise


def _validate_backend(path: str, expected_sha256: str) -> _BackendIdentity:
    fd, identity = _open_validated_backend(path, expected_sha256)
    os.close(fd)
    return identity


def _fd_mount_id(fd: int) -> int:
    try:
        with open(f"/proc/self/fdinfo/{fd}", "r", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("mnt_id:"):
                    value = line.partition(":")[2].strip()
                    if value.isdecimal():
                        return int(value)
    except OSError as error:
        raise BackendValidationError(
            f"cannot resolve rootfs mount identity: {error}"
        ) from error
    raise BackendValidationError("cannot resolve rootfs mount identity")


def _rootfs_identity_from_fd(fd: int) -> _RootfsIdentity:
    info = os.fstat(fd)
    if not stat.S_ISDIR(info.st_mode):
        raise BackendValidationError("rootfs must be a real directory")
    if info.st_uid != 0:
        raise BackendValidationError("Linux rootfs must be owned by root (uid 0)")
    if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise BackendValidationError("Linux rootfs must not be group/world writable")
    readonly_flag = getattr(os, "ST_RDONLY", 1)
    read_only_mount = bool(os.fstatvfs(fd).f_flag & readonly_flag)
    if not read_only_mount:
        raise BackendValidationError(
            "rootfs must be backed by a read-only mount; OCI readonly=true alone "
            "does not make the host source immutable"
        )
    return _RootfsIdentity(
        device=int(info.st_dev),
        inode=int(info.st_ino),
        mode=int(info.st_mode),
        uid=int(info.st_uid),
        gid=int(info.st_gid),
        mount_id=_fd_mount_id(fd),
        read_only_mount=True,
    )


def _open_validated_rootfs(
    path: str,
    expected_identity: _RootfsIdentity | None = None,
) -> tuple[int, _RootfsIdentity]:
    rootfs = _require_absolute_unaliased(path, "rootfs_path")
    if os.path.normcase(rootfs) == os.path.normcase(os.path.abspath(os.sep)):
        raise BackendValidationError("host filesystem root cannot be used as Tier-2 rootfs")
    parent_fd, name = _open_protected_parent(rootfs, "rootfs_path")
    try:
        try:
            fd = os.open(
                name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
                dir_fd=parent_fd,
            )
        except OSError as error:
            raise BackendValidationError(f"rootfs is unavailable: {error}") from error
    finally:
        os.close(parent_fd)
    try:
        identity = _rootfs_identity_from_fd(fd)
        if expected_identity is not None and identity != expected_identity:
            raise BackendValidationError("rootfs mount identity changed after composition")
        return fd, identity
    except Exception:
        os.close(fd)
        raise


def _validate_rootfs(path: str) -> _RootfsIdentity:
    fd, identity = _open_validated_rootfs(path)
    os.close(fd)
    return identity


def _validate_limits(timeout: float, max_output_bytes: int) -> None:
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise ValueError("timeout must be a finite number of seconds")
    numeric_timeout = float(timeout)
    if not (numeric_timeout > 0 and numeric_timeout <= MAX_TIMEOUT_SECONDS):
        raise ValueError(f"timeout must be in (0, {MAX_TIMEOUT_SECONDS}]")
    if isinstance(max_output_bytes, bool) or not isinstance(max_output_bytes, int):
        raise ValueError("max_output_bytes must be an integer")
    if not (1 <= max_output_bytes <= MAX_OUTPUT_BYTES):
        raise ValueError(f"max_output_bytes must be in [1, {MAX_OUTPUT_BYTES}]")


def _encode_code(code: str) -> bytes:
    if not isinstance(code, str):
        raise TypeError("code must be a string")
    # UTF-8 is at least one byte per code point.  Reject obviously oversized
    # input before allocating a second, potentially huge byte buffer.
    if len(code) > MAX_CODE_BYTES:
        raise ValueError(f"code exceeds MAX_CODE_BYTES ({MAX_CODE_BYTES})")
    try:
        encoded = code.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise ValueError("code must be valid UTF-8 text") from error
    if len(encoded) > MAX_CODE_BYTES:
        raise ValueError(f"code exceeds MAX_CODE_BYTES ({MAX_CODE_BYTES})")
    return encoded


def _acquire_run_slot() -> None:
    if not _RUN_SLOTS.acquire(blocking=False):
        raise Tier2CapacityExceeded(
            f"Tier-2 concurrency limit ({MAX_CONCURRENT_RUNS}) is exhausted"
        )


def _release_run_slot() -> None:
    _RUN_SLOTS.release()


def _accepted_result_flags(_completed: bool, *_untrusted: object) -> tuple[bool, bool]:
    """Local execution can never self-attest isolation or egress denial."""
    return False, False


def select_mechanism(*_args: object, **_kwargs: object) -> str:
    """Disabled compatibility API: PATH-based backend discovery is forbidden."""
    raise UnsafeModeDisabled(
        "backend discovery is disabled; construct Tier2Runner with an absolute "
        "runsc path and pinned SHA-256"
    )


def _terminate_process(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except (OSError, ProcessLookupError):
        try:
            proc.kill()
        except OSError:
            pass


def _run_bounded(
    command: Sequence[str],
    timeout: float,
    max_output_bytes: int,
    *,
    cwd: str | None = None,
    environment: Mapping[str, str] | None = None,
    pass_fds: Sequence[int] = (),
) -> _ProcessOutcome:
    """Run an absolute executable with bounded capture and no preexec hook."""
    _validate_limits(timeout, max_output_bytes)
    if not command or not isinstance(command[0], str) or not os.path.isabs(command[0]):
        raise BackendValidationError("command executable must be an absolute path")
    if pass_fds and os.name != "posix":
        raise BackendValidationError("descriptor-pinned execution requires POSIX")
    if any(isinstance(fd, bool) or not isinstance(fd, int) or fd < 0 for fd in pass_fds):
        raise BackendValidationError("pass_fds must contain open non-negative descriptors")
    popen_kwargs: dict[str, object] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "bufsize": 0,
        "shell": False,
        "close_fds": True,
        "cwd": cwd,
        # Empty by default: the trusted host wrapper never receives service
        # secrets or PATH.  OCI child environment is separately explicit.
        "env": dict(environment or {}),
    }
    if os.name == "posix":
        popen_kwargs["start_new_session"] = True
        popen_kwargs["pass_fds"] = tuple(pass_fds)
    elif hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    proc = subprocess.Popen(list(command), **popen_kwargs)  # type: ignore[arg-type]
    captures: dict[str, bytearray] = {"stdout": bytearray(), "stderr": bytearray()}
    truncated = {"stdout": False, "stderr": False}

    def drain(name: str, stream: BinaryIO) -> None:
        try:
            while True:
                chunk = stream.read(8192)
                if not chunk:
                    return
                remaining = max_output_bytes - len(captures[name])
                if remaining > 0:
                    captures[name].extend(chunk[:remaining])
                if len(chunk) > max(remaining, 0):
                    truncated[name] = True
        except (OSError, ValueError):
            return

    assert proc.stdout is not None and proc.stderr is not None
    readers = [
        threading.Thread(target=drain, args=("stdout", proc.stdout), daemon=True),
        threading.Thread(target=drain, args=("stderr", proc.stderr), daemon=True),
    ]
    for reader in readers:
        reader.start()

    timed_out = False
    try:
        proc.wait(timeout=float(timeout))
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate_process(proc)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _terminate_process(proc)

    for reader in readers:
        reader.join(timeout=5)
    for stream in (proc.stdout, proc.stderr):
        try:
            stream.close()
        except OSError:
            pass

    return _ProcessOutcome(
        stdout=bytes(captures["stdout"]).decode("utf-8", errors="replace"),
        stderr=bytes(captures["stderr"]).decode("utf-8", errors="replace"),
        exit_code=124 if timed_out else int(proc.returncode),
        stdout_truncated=truncated["stdout"],
        stderr_truncated=truncated["stderr"],
        timed_out=timed_out,
    )


def build_oci_bundle(script_path: str, bundle_dir: str, rootfs: str) -> str:
    """Write the fixed runsc OCI profile; this is not runtime attestation."""
    script_path = os.path.abspath(script_path)
    bundle_dir = os.path.abspath(bundle_dir)
    rootfs = os.path.abspath(rootfs)
    os.makedirs(bundle_dir, exist_ok=False)
    spec = {
        "ociVersion": "1.0.2",
        "process": {
            "terminal": False,
            "user": {"uid": 65534, "gid": 65534},
            "args": ["/usr/bin/python3", "-I", "-S", "-B", "/work/task.py"],
            "env": ["PATH=/usr/bin:/bin", "HOME=/work", "PYTHONDONTWRITEBYTECODE=1"],
            "cwd": "/work",
            "capabilities": {
                "bounding": [],
                "effective": [],
                "permitted": [],
                "inheritable": [],
                "ambient": [],
            },
            "rlimits": [
                {"type": "RLIMIT_NOFILE", "hard": 1024, "soft": 1024},
                {"type": "RLIMIT_NPROC", "hard": MAX_PROCESSES, "soft": MAX_PROCESSES},
                {"type": "RLIMIT_FSIZE", "hard": MAX_FILE_BYTES, "soft": MAX_FILE_BYTES},
                {"type": "RLIMIT_AS", "hard": MAX_MEMORY_BYTES, "soft": MAX_MEMORY_BYTES},
                {"type": "RLIMIT_CPU", "hard": 301, "soft": 301},
            ],
            "noNewPrivileges": True,
        },
        "root": {"path": rootfs, "readonly": True},
        "hostname": "tier2",
        "mounts": [
            {"destination": "/proc", "type": "proc", "source": "proc"},
            {
                "destination": "/dev",
                "type": "tmpfs",
                "source": "tmpfs",
                "options": ["nosuid", "strictatime", "mode=755", "size=65536k"],
            },
            {
                "destination": "/work/task.py",
                "type": "bind",
                "source": script_path,
                "options": ["ro", "bind", "nosuid", "nodev"],
            },
            {
                "destination": "/work/out",
                "type": "tmpfs",
                "source": "tmpfs",
                "options": ["nosuid", "nodev", "noexec", "mode=700", "size=65536k"],
            },
            {
                "destination": "/tmp",
                "type": "tmpfs",
                "source": "tmpfs",
                "options": ["nosuid", "nodev", "noexec", "mode=1777", "size=65536k"],
            },
        ],
        "linux": {
            "namespaces": [
                {"type": "pid"},
                {"type": "ipc"},
                {"type": "uts"},
                {"type": "mount"},
                {"type": "network"},
            ],
            "resources": {
                "pids": {"limit": MAX_PROCESSES},
                "memory": {"limit": MAX_MEMORY_BYTES},
                "cpu": {"quota": 100000, "period": 100000},
            },
            "maskedPaths": [
                "/proc/kcore",
                "/proc/keys",
                "/proc/timer_list",
                "/sys/firmware",
                "/proc/sched_debug",
            ],
            "readonlyPaths": [
                "/proc/sys",
                "/proc/sysrq-trigger",
                "/proc/irq",
                "/proc/bus",
            ],
        },
    }
    with open(os.path.join(bundle_dir, "config.json"), "x", encoding="utf-8") as handle:
        json.dump(spec, handle, indent=2)
    return bundle_dir


@dataclass(frozen=True, init=False, slots=True)
class Tier2Runner:
    """Pinned, runsc-only executor with bounded process-global concurrency."""

    _backend_path: str
    _expected_sha256: str
    _rootfs_path: str
    _backend_identity: _BackendIdentity
    _rootfs_identity: _RootfsIdentity

    def __init__(
        self,
        backend_path: str,
        expected_sha256: str,
        rootfs_path: str,
    ) -> None:
        pinned_backend = _require_absolute_unaliased(backend_path, "backend_path")
        pinned_digest = _normalize_sha256(expected_sha256)
        pinned_rootfs = _require_absolute_unaliased(rootfs_path, "rootfs_path")
        if not _host_supports_tier2():
            raise NoSandboxAvailable("Tier-2 execution is supported only on Linux")
        identity = _validate_backend(pinned_backend, pinned_digest)
        rootfs_identity = _validate_rootfs(pinned_rootfs)
        object.__setattr__(self, "_backend_path", pinned_backend)
        object.__setattr__(self, "_expected_sha256", pinned_digest)
        object.__setattr__(self, "_rootfs_path", pinned_rootfs)
        object.__setattr__(self, "_backend_identity", identity)
        object.__setattr__(self, "_rootfs_identity", rootfs_identity)

    def _open_backend_for_exec(self) -> int:
        fd, _identity = _open_validated_backend(
            self._backend_path,
            self._expected_sha256,
            self._backend_identity,
        )
        return fd

    def _open_rootfs_for_exec(self) -> int:
        fd, _identity = _open_validated_rootfs(
            self._rootfs_path,
            self._rootfs_identity,
        )
        return fd

    def run(
        self,
        code: str,
        timeout: float = 15,
        max_output_bytes: int = DEFAULT_OUTPUT_BYTES,
    ) -> RunResult:
        _validate_limits(timeout, max_output_bytes)
        code_bytes = _encode_code(code)
        _acquire_run_slot()
        try:
            backend_fd = self._open_backend_for_exec()
            try:
                rootfs_fd = self._open_rootfs_for_exec()
                try:
                    return self._run_with_slot(
                        code_bytes,
                        timeout,
                        max_output_bytes,
                        backend_fd,
                        rootfs_fd,
                    )
                finally:
                    os.close(rootfs_fd)
            finally:
                os.close(backend_fd)
        finally:
            _release_run_slot()

    def _run_with_slot(
        self,
        code_bytes: bytes,
        timeout: float,
        max_output_bytes: int,
        backend_fd: int,
        rootfs_fd: int,
    ) -> RunResult:
        work = tempfile.mkdtemp(prefix="tier2_")
        script = os.path.join(work, "task.py")
        container_id: str | None = None
        try:
            with open(script, "xb") as handle:
                handle.write(code_bytes)
            # The temp directory itself is private to the service.  The bind
            # source must still be readable by OCI uid 65534 after mounting.
            os.chmod(script, 0o444)
            # Both security-sensitive path targets stay pinned as inherited
            # descriptors for the full runsc invocation.  runsc never resolves
            # the validated backend or rootfs through their original names.
            backend_exec = f"/proc/self/fd/{backend_fd}"
            rootfs_source = f"/proc/self/fd/{rootfs_fd}"
            bundle = build_oci_bundle(
                script, os.path.join(work, "bundle"), rootfs_source
            )
            container_id = f"tier2-{uuid.uuid4().hex}"
            command = [
                backend_exec,
                "--network=none",
                "run",
                "--bundle",
                bundle,
                container_id,
            ]
            outcome = _run_bounded(
                command,
                timeout,
                max_output_bytes,
                cwd=work,
                environment={},
                pass_fds=(backend_fd, rootfs_fd),
            )
            completed = outcome.exit_code == 0 and not outcome.timed_out
            isolated, egress_denied = _accepted_result_flags(completed)
            return RunResult(
                ok=completed,
                mechanism="runsc",
                stdout=outcome.stdout,
                stderr=outcome.stderr,
                exit_code=outcome.exit_code,
                isolated=isolated,
                egress_denied=egress_denied,
                stdout_truncated=outcome.stdout_truncated,
                stderr_truncated=outcome.stderr_truncated,
                timed_out=outcome.timed_out,
            )
        finally:
            if container_id is not None:
                try:
                    subprocess.run(
                        [
                            f"/proc/self/fd/{backend_fd}",
                            "delete",
                            "--force",
                            container_id,
                        ],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=5,
                        check=False,
                        shell=False,
                        close_fds=True,
                        pass_fds=(backend_fd,),
                        cwd=work,
                        env={},
                    )
                except (OSError, subprocess.SubprocessError, BackendValidationError):
                    pass
            # Python cleanup only; no backend or shell lookup is involved.
            import shutil

            shutil.rmtree(work, ignore_errors=True)


def run(*_args: object, **_kwargs: object) -> RunResult:
    """Removed compatibility entry point; explicit composition is required."""
    raise UnsafeModeDisabled(
        "legacy module-level run is disabled; construct a pinned Tier2Runner"
    )
