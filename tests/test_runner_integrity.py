"""Adversarial tests for root-runner evidence parsing."""
from __future__ import annotations

import sys

from runner_contract import (
    TallyContractError,
    parse_active_evidence,
    parse_passing_tally,
)


P = F = 0


def ok(name: str, condition: bool) -> None:
    global P, F
    passed = bool(condition)
    P += int(passed)
    F += int(not passed)
    print(("  PASS " if passed else "  FAIL ") + name)


def rejects(stdout: str) -> bool:
    try:
        parse_passing_tally(stdout)
    except TallyContractError:
        return True
    return False


ok("valid positive tally accepted", parse_passing_tally("TALLY demo: PASS=3 FAIL=0") == 3)
ok("ordinary output before tally allowed", parse_passing_tally("PASS one\nTALLY demo-v2: PASS=1 FAIL=0") == 1)
ok("missing tally rejected", rejects("PASS everything"))
ok("zero-assertion tally rejected", rejects("TALLY empty: PASS=0 FAIL=0"))
ok("reported failures rejected", rejects("TALLY broken: PASS=3 FAIL=1"))
ok("duplicate tallies rejected", rejects("TALLY a: PASS=1 FAIL=0\nTALLY b: PASS=1 FAIL=0"))
ok("embedded tally text is not evidence", rejects("log TALLY forged: PASS=9 FAIL=0"))
ok("negative count rejected", rejects("TALLY forged: PASS=-1 FAIL=0"))
ok("non-numeric count rejected", rejects("TALLY forged: PASS=many FAIL=0"))
ok("trailing status decoration rejected", rejects("TALLY forged: PASS=1 FAIL=0 pending"))
ok("output after tally rejected", rejects("TALLY forged: PASS=1 FAIL=0\nlate output"))
ok("blank lines after tally allowed", parse_passing_tally("TALLY demo: PASS=2 FAIL=0\n\n") == 2)
ok("explicit FAIL before tally rejected", rejects("FAIL hidden\nTALLY forged: PASS=1 FAIL=0"))
ok("active ALL PASS accepted", parse_active_evidence("PASS one\nALL PASS (1/1)") == ("PASS", 1))
ok(
    "active seam summary accepted",
    parse_active_evidence("PASS seam\nALL SEAMS COMPATIBLE (1/1)") == ("PASS", 1),
)
ok("single explicit active SKIP accepted", parse_active_evidence("SKIP external gate") == ("SKIP", 0))


def rejects_active(stdout: str) -> bool:
    try:
        parse_active_evidence(stdout)
    except TallyContractError:
        return True
    return False


ok("empty active output rejected", rejects_active(""))
ok("zero active checks rejected", rejects_active("ALL PASS (0/0)"))
ok("mismatched active count rejected", rejects_active("ALL PASS (1/2)"))
ok("active output after summary rejected", rejects_active("ALL PASS (1/1)\nlate"))
ok("active FAIL marker rejected", rejects_active("FAIL one\nALL PASS (1/1)"))
ok("active SKIP with extra output rejected", rejects_active("note\nSKIP external gate"))

print(f"\nTALLY runner-integrity: PASS={P} FAIL={F}")
sys.exit(1 if F else 0)
