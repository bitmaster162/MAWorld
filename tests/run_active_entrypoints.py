"""Run every active app/service Python acceptance entrypoint fail-closed.

This complements ``tests/run_all.py``.  Each script runs in its own directory
with the canonical ``libs`` directory first on ``PYTHONPATH`` and with bytecode
writes disabled, so the result is reproducible from any caller working dir.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from runner_contract import TallyContractError, parse_active_evidence


ROOT = Path(__file__).resolve().parents[1]
LIBS = ROOT / "libs"
ENTRYPOINTS = sorted(
    list((ROOT / "apps").rglob("test_*.py"))
    + list((ROOT / "services").rglob("test_*.py"))
)
ENV = dict(
    os.environ,
    PYTHONPATH=str(LIBS) + os.pathsep + os.environ.get("PYTHONPATH", ""),
    PYTHONIOENCODING="utf-8",
    PYTHONUTF8="1",
    PYTHONDONTWRITEBYTECODE="1",
)


def main() -> int:
    green = 0
    skipped_suites = 0
    printed_checks = 0
    failed: list[str] = []
    if not ENTRYPOINTS:
        print("FAIL no active entrypoints discovered", file=sys.stderr)
        return 1
    for script in ENTRYPOINTS:
        relative = script.relative_to(ROOT).as_posix()
        try:
            result = subprocess.run(
                [sys.executable, str(script)],
                cwd=script.parent,
                env=ENV,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            failed.append(relative)
            print(f"  FAIL {relative} <- exceeded 60s timeout")
            continue
        try:
            evidence, checks = parse_active_evidence(result.stdout)
        except TallyContractError as error:
            evidence, checks = "FAIL", 0
            contract_error = str(error)
        else:
            contract_error = ""
        if result.returncode == 0 and evidence == "SKIP":
            skipped_suites += 1
            print(f"  SKIP {relative}  (explicit external gate)")
        elif result.returncode == 0 and evidence == "PASS":
            green += 1
            printed_checks += checks
            print(f"  OK   {relative}  ({checks})")
        else:
            failed.append(relative)
            detail = contract_error or f"exit={result.returncode}"
            print(
                f"  FAIL {relative} <- {detail}\n"
                f"{result.stdout[-1200:]}{result.stderr[-600:]}"
            )
    print(
        f"\n== active entrypoints: {green}/{len(ENTRYPOINTS)} green"
        f" · skipped suites={skipped_suites} · {printed_checks} printed checks =="
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
