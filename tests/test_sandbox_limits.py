import os
import sys
import tempfile

from sandbox_limits import (
    ResourceLimitsUnavailable, resource_limits_available, run_limited,
)

P = F = 0


def ok(name, condition, detail=""):
    global P, F
    passed = bool(condition)
    P += passed
    F += not passed
    print(("  PASS " if passed else "  FAIL ") + name + ("" if passed else f" <- {detail}"))


if not resource_limits_available():
    sentinel = os.path.join(tempfile.mkdtemp(), "must-not-exist")
    code = f"open({sentinel!r}, 'w').write('executed')"
    try:
        run_limited(code)
        refused = False
    except ResourceLimitsUnavailable:
        refused = True
    ok("unsupported host refuses before child execution", refused and not os.path.exists(sentinel))
    ok("resource backend honestly reports unavailable", resource_limits_available() is False)
else:
    cpu = run_limited("x=0\nwhile True:\n x+=1", cpu_s=1, timeout=8)
    ok("CPU-bound loop is killed by kernel limit", not cpu.ok)

    memory = run_limited(
        "b=bytearray(500*1024*1024)\nprint('alloc-ok')",
        mem_mb=64,
        cpu_s=3,
        timeout=8,
    )
    ok("over-memory allocation is rejected", not memory.ok and "alloc-ok" not in memory.stdout)

    output = run_limited("print('A'*200000)", max_output=1000, cpu_s=3)
    ok("output is kernel-capped without RAM buffering", output.output_truncated and len(output.stdout.encode()) <= 1000)

    normal = run_limited("print('hello')", cpu_s=2)
    ok("normal resource-limited job runs", normal.ok and "hello" in normal.stdout)
    ok("resource limiter never claims filesystem/network isolation", normal.resource_limited and not normal.isolated)

    first = run_limited("print(1)")
    second = run_limited("print(1)")
    ok("unique job id per run", first.container_id != second.container_id)

print(f"\nTALLY sandbox-limits: PASS={P} FAIL={F}")
sys.exit(1 if F else 0)
