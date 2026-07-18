"""Audit every package/version branch in committed Python locks against OSV.

Unlike installer-oriented tools, this deliberately ignores environment markers
while collecting versions. Universal lock branches for other Python versions
and operating systems are therefore included in one query.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCKS = tuple(sorted((ROOT / "requirements").glob("*.lock.txt")))
REQUIREMENT = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s;\\]+)")
OSV_BATCH_URL = "https://api.osv.dev/v1/querybatch"


def locked_pairs() -> list[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for lock in LOCKS:
        for line in lock.read_text(encoding="utf-8").splitlines():
            match = REQUIREMENT.match(line)
            if match:
                name = re.sub(r"[-_.]+", "-", match.group(1)).lower()
                pairs.add((name, match.group(2)))
    if not pairs:
        raise ValueError("no package/version pairs found in committed locks")
    return sorted(pairs)


def main() -> int:
    pairs = locked_pairs()
    payload = json.dumps(
        {
            "queries": [
                {"package": {"ecosystem": "PyPI", "name": name}, "version": version}
                for name, version in pairs
            ]
        },
        separators=(",", ":"),
    ).encode("utf-8")
    request = urllib.request.Request(
        OSV_BATCH_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "MAWorld-lock-audit/1",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        result = json.load(response)
    rows = result.get("results")
    if not isinstance(rows, list) or len(rows) != len(pairs):
        raise ValueError("OSV returned an incomplete batch response")

    findings: list[tuple[str, str, str]] = []
    for (name, version), row in zip(pairs, rows, strict=True):
        for vulnerability in row.get("vulns", ()):
            identifier = vulnerability.get("id", "UNKNOWN")
            findings.append((name, version, identifier))
    if findings:
        for name, version, identifier in findings:
            print(f"VULNERABLE {name}=={version} {identifier}")
        print(
            f"FAIL OSV lock audit: pairs={len(pairs)} findings={len(findings)}",
            file=sys.stderr,
        )
        return 1
    print(f"PASS OSV lock audit: pairs={len(pairs)} findings=0")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as error:
        print(f"FAIL OSV lock audit: {error}", file=sys.stderr)
        raise SystemExit(2)
