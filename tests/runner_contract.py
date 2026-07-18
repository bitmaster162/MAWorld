"""Strict evidence contract shared by the root adversarial runner."""
from __future__ import annotations

import re


TALLY_RE = re.compile(
    r"^TALLY [A-Za-z0-9+_. -]+: PASS=(0|[1-9][0-9]*) FAIL=(0|[1-9][0-9]*)$"
)
ALL_PASS_RE = re.compile(r"^ALL PASS \(([1-9][0-9]*)/([1-9][0-9]*)\)$")
ALL_SEAMS_RE = re.compile(
    r"^ALL SEAMS COMPATIBLE \(([1-9][0-9]*)/([1-9][0-9]*)\)$"
)


class TallyContractError(ValueError):
    pass


def parse_passing_tally(stdout: str) -> int:
    if any(re.match(r"^\s*FAIL\b", line) for line in stdout.splitlines()):
        raise TallyContractError("output contains an explicit FAIL marker")
    nonempty_lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    tally_positions = [
        (index, line)
        for index, line in enumerate(nonempty_lines)
        if line.startswith("TALLY")
    ]
    if len(tally_positions) != 1:
        raise TallyContractError(
            f"expected exactly one terminal TALLY, found {len(tally_positions)}"
        )
    position, tally = tally_positions[0]
    if position != len(nonempty_lines) - 1:
        raise TallyContractError("TALLY must be the last non-empty output line")
    match = TALLY_RE.fullmatch(tally)
    if match is None:
        raise TallyContractError("malformed terminal TALLY")
    passed, failed = (int(value) for value in match.groups())
    if passed <= 0:
        raise TallyContractError("zero-assertion suites are forbidden")
    if failed != 0:
        raise TallyContractError("suite reports failed assertions")
    return passed


def parse_active_evidence(stdout: str) -> tuple[str, int]:
    """Return (PASS|SKIP, checks) for one active entrypoint's terminal evidence."""
    nonempty_lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not nonempty_lines:
        raise TallyContractError("active entrypoint produced no evidence")
    if any(re.match(r"^FAIL\b", line) for line in nonempty_lines):
        raise TallyContractError("output contains an explicit FAIL marker")
    if any(line.startswith("TALLY") for line in nonempty_lines):
        return "PASS", parse_passing_tally(stdout)
    if len(nonempty_lines) == 1 and re.fullmatch(r"SKIP\s+\S.*", nonempty_lines[0]):
        return "SKIP", 0

    terminal = nonempty_lines[-1]
    match = ALL_PASS_RE.fullmatch(terminal) or ALL_SEAMS_RE.fullmatch(terminal)
    if match is None:
        raise TallyContractError("missing strict terminal PASS/SKIP evidence")
    passed, total = (int(value) for value in match.groups())
    if passed != total:
        raise TallyContractError("terminal PASS count does not equal total")
    return "PASS", passed


__all__ = ["TallyContractError", "parse_active_evidence", "parse_passing_tally"]
