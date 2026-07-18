"""POSIX process resource limiter; deliberately not an isolation sandbox.

The limiter applies kernel CPU/address-space/file-size limits and bounds captured
output without buffering an untrusted stream in memory.  It does *not* isolate
filesystem or network access.  On hosts without the POSIX ``resource`` backend
(including Windows), execution fails closed before a child process is created.
Production arbitrary-code execution still requires a separate runsc/VM/AppContainer
adapter with filesystem and egress isolation.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass

try:
    import resource
except ImportError:  # Windows has no POSIX rlimit backend.
    resource = None


class ResourceLimitsUnavailable(RuntimeError):
    pass


def resource_limits_available() -> bool:
    return os.name == "posix" and resource is not None and hasattr(os, "setsid")


@dataclass
class LimitedResult:
    ok: bool
    container_id: str
    exit_code: int
    signal: int
    stdout: str
    stderr: str
    output_truncated: bool
    resource_limited: bool = True
    isolated: bool = False


def _preexec(cpu_s: int, mem_bytes: int, max_output: int):
    def apply_limits():
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s))
        if mem_bytes:
            resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
        resource.setrlimit(resource.RLIMIT_FSIZE, (max_output, max_output))
        if hasattr(resource, "RLIMIT_CORE"):
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        if hasattr(resource, "RLIMIT_NOFILE"):
            resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
        if hasattr(resource, "RLIMIT_NPROC"):
            resource.setrlimit(resource.RLIMIT_NPROC, (1, 1))
        os.setsid()

    return apply_limits


def _bounded_read(path: str, limit: int) -> tuple[str, bool]:
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            raw = handle.read(limit)
        return raw.decode("utf-8", "replace"), size >= limit
    except OSError:
        return "", False


def run_limited(
    code: str,
    cpu_s: int = 2,
    mem_mb: int = 256,
    max_output: int = 64 * 1024,
    timeout: int = 10,
    max_code_bytes: int = 256 * 1024,
) -> LimitedResult:
    """Run Python with POSIX rlimits, or refuse before execution.

    ``isolated`` is always false: resource limits alone are not a security
    boundary for arbitrary code.
    """
    if not resource_limits_available():
        raise ResourceLimitsUnavailable(
            "POSIX resource-limit backend unavailable; no child was started"
        )
    if not isinstance(code, str):
        raise TypeError("code must be a string")
    encoded = code.encode("utf-8")
    if len(encoded) > max_code_bytes:
        raise ValueError("code exceeds max_code_bytes")
    for name, value in (
        ("cpu_s", cpu_s), ("mem_mb", mem_mb),
        ("max_output", max_output), ("timeout", timeout),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"{name} must be a positive integer")

    container_id = "job-" + uuid.uuid4().hex
    work = tempfile.mkdtemp(prefix="maworld-limits-")
    script = os.path.join(work, "task.py")
    stdout_path = os.path.join(work, "stdout.bin")
    stderr_path = os.path.join(work, "stderr.bin")
    process = None
    timed_out = False
    return_code = 125
    try:
        with open(script, "wb") as handle:
            handle.write(encoded)
        with open(stdout_path, "w+b") as stdout_file, open(stderr_path, "w+b") as stderr_file:
            process = subprocess.Popen(
                [sys.executable, "-I", "-S", "-B", script],
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                cwd=work,
                shell=False,
                preexec_fn=_preexec(cpu_s, mem_mb * 1024 * 1024, max_output),
                close_fds=True,
            )
            try:
                return_code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    process.kill()
                return_code = process.wait()

        stdout, stdout_truncated = _bounded_read(stdout_path, max_output)
        stderr, stderr_truncated = _bounded_read(stderr_path, max_output)
        if timed_out:
            return LimitedResult(
                False, container_id, 124, 0, stdout, "TIMEOUT" + (": " + stderr if stderr else ""),
                stdout_truncated or stderr_truncated,
            )
        signal_number = -return_code if return_code < 0 else 0
        return LimitedResult(
            return_code == 0,
            container_id,
            return_code,
            signal_number,
            stdout,
            stderr,
            stdout_truncated or stderr_truncated,
        )
    finally:
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                process.kill()
            process.wait()
        shutil.rmtree(work, ignore_errors=True)
