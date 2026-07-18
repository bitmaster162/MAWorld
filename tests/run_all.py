"""Unified adversarial runner with a strict, positive evidence contract."""
import glob
import os
import subprocess
import sys

from runner_contract import TallyContractError, parse_passing_tally


ROOT = os.path.dirname(os.path.abspath(__file__))
LIBS = os.path.abspath(os.path.join(ROOT, "..", "libs"))
SUITE_TIMEOUT_S = 60
env = dict(
    os.environ,
    PYTHONPATH=LIBS + os.pathsep + os.environ.get("PYTHONPATH", ""),
    PYTHONIOENCODING="utf-8",
    PYTHONUTF8="1",
    PYTHONDONTWRITEBYTECODE="1",
)
suites = sorted(glob.glob(os.path.join(ROOT, "test_*.py")))
green = 0
total_assert = 0
failed = []
if not suites:
    print("FAIL no adversarial suites discovered", file=sys.stderr)
    raise SystemExit(1)
for s in suites:
    name = os.path.basename(s)
    try:
        result = subprocess.run(
            [sys.executable, s],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=SUITE_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as error:
        failed.append(name)
        print(f"  FAIL {name} <- exceeded {SUITE_TIMEOUT_S}s timeout")
        continue
    try:
        assertions = parse_passing_tally(result.stdout)
    except TallyContractError as error:
        assertions = 0
        contract_error = str(error)
    else:
        contract_error = ""
    if result.returncode == 0 and not contract_error:
        green += 1
        total_assert += assertions
        print(f"  OK   {name}  ({assertions})")
    else:
        failed.append(name)
        detail = contract_error or f"exit={result.returncode}"
        print(
            f"  FAIL {name} <- {detail}\n"
            f"{result.stdout[-400:]}{result.stderr[-200:]}"
        )
print(f"\n== {green}/{len(suites)} suites green · {total_assert} adversarial assertions ==")
sys.exit(1 if failed else 0)
