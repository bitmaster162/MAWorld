"""Portable invariant checks for the pinned, fail-closed Tier-2 runner.

Local probes are deliberately not security attestations.  Functional runsc
smoke checks run only when an explicit backend path, digest, and rootfs are
provided on Linux.  Production isolation, egress, and host-confinement claims
remain SKIP until verified by a separate fixed-key signed-evidence boundary.
"""
from __future__ import annotations

import inspect
import json
import os
import sys
import tempfile

import tier2_runner as T


passed = failed = skipped = 0


def check(name: str, condition: object, detail: object = "") -> None:
    global passed, failed
    ok = bool(condition)
    passed += int(ok)
    failed += int(not ok)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else f" <- {detail}"))


def skip(name: str, reason: str) -> None:
    global skipped
    skipped += 1
    print(f"  SKIP {name} <- {reason}")


print("== Tier-2 pinned-backend invariant checks ==")

# Every legacy discovery/fallback spelling is disabled.
for name, call in (
    ("PATH backend discovery is disabled", lambda: T.select_mechanism()),
    ("strict=False cannot enable a fallback", lambda: T.select_mechanism(strict=False)),
    ("module-level execution is disabled", lambda: T.run("print('unsafe')")),
):
    try:
        call()
        rejected = False
    except T.UnsafeModeDisabled:
        rejected = True
    check(name, rejected)

# A malicious binary placed first on PATH is neither selected nor executed.
fake_root = tempfile.mkdtemp(prefix="tier2_fake_path_")
fake_backend = os.path.join(fake_root, "runsc.exe" if os.name == "nt" else "runsc")
marker = os.path.join(fake_root, "EXECUTED")
with open(fake_backend, "w", encoding="utf-8") as handle:
    handle.write("fake backend")
old_path = os.environ.get("PATH")
try:
    os.environ["PATH"] = fake_root + os.pathsep + (old_path or "")
    try:
        T.select_mechanism()
        fake_rejected = False
    except T.UnsafeModeDisabled:
        fake_rejected = True
finally:
    if old_path is None:
        os.environ.pop("PATH", None)
    else:
        os.environ["PATH"] = old_path
check("a fake PATH backend is ignored", fake_rejected and not os.path.exists(marker))

try:
    T.Tier2Runner("runsc", "0" * 64, os.path.abspath(fake_root))
    relative_rejected = False
except T.BackendValidationError:
    relative_rejected = True
check("runner requires an absolute backend path", relative_rejected)

try:
    T.Tier2Runner(os.path.abspath(fake_backend), "not-a-digest", os.path.abspath(fake_root))
    digest_rejected = False
except ValueError:
    digest_rejected = True
check("runner requires an exact SHA-256 pin", digest_rejected)

if not T._host_supports_tier2():
    try:
        T.Tier2Runner(os.path.abspath(fake_backend), "0" * 64, os.path.abspath(fake_root))
        platform_rejected = False
    except T.NoSandboxAvailable:
        platform_rejected = True
    check("unsupported hosts (including Windows) fail closed", platform_rejected)
else:
    check("host platform gate identifies Linux", True)

# The host wrapper accepts only absolute executables and clears inherited env.
try:
    T._run_bounded(["python", "-c", "print(1)"], timeout=1, max_output_bytes=1024)
    relative_command_rejected = False
except T.BackendValidationError:
    relative_command_rejected = True
check("host wrapper cannot perform PATH lookup", relative_command_rejected)

os.environ["TIER2_SHOULD_NOT_LEAK"] = "secret"
try:
    clean_env = T._run_bounded(
        [
            os.path.abspath(sys.executable),
            "-I",
            "-S",
            "-c",
            "import os;print(os.getenv('TIER2_SHOULD_NOT_LEAK','CLEARED'))",
        ],
        timeout=10,
        max_output_bytes=1024,
    )
finally:
    os.environ.pop("TIER2_SHOULD_NOT_LEAK", None)
check("host backend environment is cleared", clean_env.stdout.strip() == "CLEARED", clean_env)

# Output and time are bounded without preexec_fn.
limit = 4096
noisy = T._run_bounded(
    [
        os.path.abspath(sys.executable),
        "-I",
        "-S",
        "-c",
        "import sys;sys.stdout.buffer.write(b'o'*20000);sys.stderr.buffer.write(b'e'*20000)",
    ],
    timeout=10,
    max_output_bytes=limit,
)
check("stdout capture is hard-bounded", len(noisy.stdout.encode()) <= limit and noisy.stdout_truncated)
check("stderr capture is hard-bounded", len(noisy.stderr.encode()) <= limit and noisy.stderr_truncated)

timed = T._run_bounded(
    [os.path.abspath(sys.executable), "-I", "-S", "-c", "while True: pass"],
    timeout=0.25,
    max_output_bytes=limit,
)
check("deadline returns an explicit timeout", timed.timed_out and timed.exit_code == 124)

try:
    T._run_bounded(
        [os.path.abspath(sys.executable), "-c", "print(1)"],
        timeout=1,
        max_output_bytes=T.MAX_OUTPUT_BYTES + 1,
    )
    excessive_output_rejected = False
except ValueError:
    excessive_output_rejected = True
check("caller cannot raise capture above the hard cap", excessive_output_rejected)

source = inspect.getsource(T)
check("multithreaded wrapper has no preexec_fn", "preexec_fn" not in source)
check("runner source has no shutil.which lookup", "shutil.which" not in source)

# Code size is measured as UTF-8 bytes before backend validation or temp writes.
check("code at MAX_CODE_BYTES is accepted by the size gate", len(T._encode_code("x" * T.MAX_CODE_BYTES)) == T.MAX_CODE_BYTES)
try:
    T._encode_code("x" * (T.MAX_CODE_BYTES + 1))
    oversized_rejected = False
except ValueError:
    oversized_rejected = True
check("code above MAX_CODE_BYTES is rejected", oversized_rejected)
check("code bound counts UTF-8 bytes", len(T._encode_code("€")) == 3)

run_source = inspect.getsource(T.Tier2Runner.run)
check(
    "code gate and concurrency cap precede backend access and execution",
    run_source.index("_encode_code")
    < run_source.index("_acquire_run_slot")
    < run_source.index("_open_backend_for_exec")
    < run_source.index("_open_rootfs_for_exec")
    < run_source.index("_run_with_slot"),
)

# Security-sensitive paths are resolved through pinned descriptors, not
# re-resolved between validation and exec.  These portable source-contract
# checks are not a substitute for the Linux runtime evidence skipped below.
parent_walk_source = inspect.getsource(T._open_protected_parent)
backend_open_source = inspect.getsource(T._open_validated_backend)
rootfs_open_source = inspect.getsource(T._open_validated_rootfs)
rootfs_identity_source = inspect.getsource(T._rootfs_identity_from_fd)
slot_source = inspect.getsource(T.Tier2Runner._run_with_slot)
check(
    "parent paths use no-follow descriptor walking",
    "dir_fd=current" in parent_walk_source
    and "os.O_NOFOLLOW" in parent_walk_source
    and "_validate_protected_directory_fd" in parent_walk_source,
)
check(
    "backend validation and exec share the pinned file descriptor",
    "dir_fd=parent_fd" in backend_open_source
    and "_backend_identity_from_fd" in backend_open_source
    and 'f"/proc/self/fd/{backend_fd}"' in slot_source
    and "pass_fds=(backend_fd, rootfs_fd)" in slot_source,
)
check(
    "rootfs is descriptor-pinned and requires a read-only mount",
    "dir_fd=parent_fd" in rootfs_open_source
    and "os.fstatvfs(fd)" in rootfs_identity_source
    and "read_only_mount" in rootfs_identity_source
    and 'f"/proc/self/fd/{rootfs_fd}"' in slot_source,
)

claims = set(T.REQUIRED_DEPLOYMENT_ATTESTATION_CLAIMS)
check(
    "external attestation contract binds backend, rootfs, policy, and host",
    {
        "backend_sha256",
        "backend_file_identity",
        "rootfs_image_digest",
        "rootfs_mount_identity",
        "oci_policy_digest",
        "host_identity",
    }.issubset(claims),
)
check(
    "external attestation contract requires freshness and replay fields",
    {"issued_at", "expires_at", "nonce"}.issubset(claims)
    and "isolation_verified" not in claims
    and "egress_denial_verified" not in claims,
)

# Bounded concurrency rejects immediately; it never queues unbounded work.
held = 0
try:
    for _ in range(T.MAX_CONCURRENT_RUNS):
        T._acquire_run_slot()
        held += 1
    try:
        T._acquire_run_slot()
        capacity_rejected = False
    except T.Tier2CapacityExceeded:
        capacity_rejected = True
finally:
    for _ in range(held):
        T._release_run_slot()
check("global concurrency cap fails closed when exhausted", capacity_rejected)

# Caller assertions cannot manufacture isolation acceptance.
try:
    T.BackendAcceptance(
        isolation_verified=False,
        egress_denial_verified=True,
    )
    invalid_acceptance_rejected = False
except (TypeError, ValueError):
    invalid_acceptance_rejected = True
check("caller booleans cannot create backend acceptance", invalid_acceptance_rejected)

try:
    T.BackendAcceptance(isolation_verified=True, egress_denial_verified=True)
    positive_acceptance_rejected = False
except TypeError:
    positive_acceptance_rejected = True
check("positive caller acceptance is hard-disabled", positive_acceptance_rejected)
check("runner composition is frozen", T.Tier2Runner.__dataclass_params__.frozen is True)

try:
    T._validate_rootfs(os.path.abspath(os.sep))
    host_root_rejected = False
except T.BackendValidationError:
    host_root_rejected = True
check("host filesystem root cannot be used as rootfs", host_root_rejected)

# A successful backend exit alone must not produce attested flags.
unattested_flags = T._accepted_result_flags(True, None)
forged_flags = T._accepted_result_flags(
    True, {"isolation_verified": True, "egress_denial_verified": True}
)
check(
    "exit zero and forged booleans never claim isolation or egress denial",
    unattested_flags == (False, False) and forged_flags == (False, False),
)

# OCI configuration checks do not imply that runsc exists or worked.
bundle_root = tempfile.mkdtemp(prefix="tier2_bundle_")
script = os.path.join(bundle_root, "task.py")
rootfs_fixture = os.path.join(bundle_root, "rootfs")
os.mkdir(rootfs_fixture)
with open(script, "w", encoding="utf-8") as handle:
    handle.write("print(1)")
T.build_oci_bundle(script, os.path.join(bundle_root, "bundle"), rootfs_fixture)
with open(os.path.join(bundle_root, "bundle", "config.json"), encoding="utf-8") as handle:
    spec = json.load(handle)
namespaces = {item["type"] for item in spec["linux"]["namespaces"]}
mounts = {item["destination"]: item for item in spec["mounts"]}
environment = spec["process"]["env"]
check("OCI config requests a separate network namespace", "network" in namespaces)
check("OCI config makes root read-only", spec["root"]["readonly"] is True)
check("OCI config uses the fixed explicit rootfs", spec["root"]["path"] == os.path.abspath(rootfs_fixture))
check("OCI config drops every capability set", all(not value for value in spec["process"]["capabilities"].values()))
check("OCI config enables noNewPrivileges", spec["process"]["noNewPrivileges"] is True)
check("OCI config runs as nobody", spec["process"]["user"] == {"uid": 65534, "gid": 65534})
check("OCI config has a pids limit", spec["linux"]["resources"]["pids"]["limit"] == T.MAX_PROCESSES)
check(
    "OCI output is ephemeral tmpfs (no host rw bind)",
    mounts["/work/out"]["type"] == "tmpfs"
    and mounts["/work/out"].get("source") == "tmpfs",
)
check("OCI config exposes source read-only", "ro" in mounts["/work/task.py"]["options"])
check("OCI child receives only the explicit environment", environment == ["PATH=/usr/bin:/bin", "HOME=/work", "PYTHONDONTWRITEBYTECODE=1"])
check("OCI config has a memory limit", spec["linux"]["resources"]["memory"]["limit"] == T.MAX_MEMORY_BYTES)
check("OCI config has a CPU quota", spec["linux"]["resources"]["cpu"] == {"quota": 100000, "period": 100000})

# Functional runtime smoke checks require explicit pinned composition.  Never
# search PATH here.  Passing them does not establish isolation or deny-egress.
backend_path = os.environ.get("TIER2_BACKEND_PATH", "")
backend_sha256 = os.environ.get("TIER2_BACKEND_SHA256", "")
rootfs_path = os.environ.get("TIER2_ROOTFS_PATH", "")
runner: T.Tier2Runner | None = None
runtime_reason = ""
if not T._host_supports_tier2():
    runtime_reason = "current host is not Linux"
elif not (backend_path and backend_sha256 and rootfs_path):
    runtime_reason = "explicit TIER2_BACKEND_PATH/SHA256/ROOTFS_PATH are not all set"
else:
    try:
        runner = T.Tier2Runner(backend_path, backend_sha256, rootfs_path)
    except T.NoSandboxAvailable as error:
        runtime_reason = str(error)

if runner is None:
    for test_name in (
        "installed pinned runsc functional smoke (not isolation evidence)",
        "installed pinned runsc functional timeout (not isolation evidence)",
    ):
        skip(test_name, runtime_reason)
else:
    result = runner.run(
        "print('RUNSC_FUNCTIONAL_SMOKE')\n",
        timeout=10,
    )
    check(
        "installed pinned runsc functional smoke (not isolation evidence)",
        "RUNSC_FUNCTIONAL_SMOKE" in result.stdout
        and result.ok
        and not result.isolated
        and not result.egress_denied,
        result,
    )
    result = runner.run("while True: pass", timeout=0.5)
    check(
        "installed pinned runsc functional timeout (not isolation evidence)",
        result.timed_out and result.exit_code == 124,
        result,
    )

# A single TCP failure or one denied /etc write cannot prove a network policy,
# mount confinement, or resistance to namespace escape.  This local suite has
# no fixed-key verifier for externally issued evidence, so these claims always
# remain explicit SKIP rather than becoming PASS from self-reported probes.
skip(
    "signed deployment attestation binds pinned backend/rootfs/policy",
    "requires external fixed-key signature verification and digest-pinned evidence",
)
skip(
    "controlled multi-vector egress-denial attestation",
    "requires controlled TCP/UDP/IPv4/IPv6/DNS endpoints plus host firewall evidence",
)
skip(
    "comprehensive host-write and namespace-confinement attestation",
    "requires mount-table/LSM/runtime evidence; one denied /etc write is insufficient",
)

print(f"\nTALLY tier2 acceptance: PASS={passed} FAIL={failed} SKIP={skipped}")
sys.exit(1 if failed else 0)
