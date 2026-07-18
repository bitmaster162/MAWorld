"""Operator Cockpit v1 offline renderer -- HTTP hard-disabled.

Manifest and acceptance files are unsigned input.  Their ``accepted`` and
``truthStatus`` fields are retained only as source metadata and can never make
a system VERIFIED.  Network serving stays disabled until a composition root
provides fixed ActionVerifier and EvidenceAcceptor dependencies.
"""
from __future__ import annotations

import html
import json
import os
import sys


HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.environ.get(
    "UNIVERSE_MANIFEST", os.path.join(HERE, "universe_manifest.json")
)
ACCEPT = os.environ.get(
    "EVIDENCE_ACCEPTANCES", os.path.join(HERE, "evidence_acceptances.json")
)

UNSIGNED_TRUTH = "UNVERIFIED/PROPOSED"
HTTP_DISABLED_REASON = (
    "Cockpit HTTP is disabled until fixed ActionVerifier and EvidenceAcceptor "
    "integration is installed"
)


def _load(path: str, default: object, errors: list[str], label: str):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception as exc:
        errors.append(f"{label}: {exc}")
        return default


def _acceptance_index(raw: object) -> dict[str, dict]:
    if not isinstance(raw, dict):
        return {}
    indexed = {}
    for item in raw.get("acceptances", []):
        if not isinstance(item, dict):
            continue
        system = item.get("system")
        if isinstance(system, str) and system:
            indexed[system] = item
    return indexed


def state() -> dict:
    """Build an offline snapshot without accepting any JSON truth claim."""

    out = {
        "systems": [],
        "errors": [],
        "http": "DISABLED",
        "verification": "UNAVAILABLE",
    }
    acceptances = _acceptance_index(
        _load(ACCEPT, {}, out["errors"], "unsigned acceptances")
    )
    manifest = _load(MANIFEST, {}, out["errors"], "unsigned manifest")
    if not isinstance(manifest, dict):
        out["errors"].append("unsigned manifest: object required")
        return out

    for source in manifest.get("systems", []):
        if not isinstance(source, dict):
            continue
        slug = source.get("slug")
        unsigned_acceptance = acceptances.get(slug, {})
        out["systems"].append(
            {
                "name": source.get("displayName"),
                "slug": slug,
                "truth": UNSIGNED_TRUTH,
                "evidence_status": "UNSIGNED_JSON",
                "unsigned_detail": unsigned_acceptance.get("detail", ""),
                "source_truth_claim": source.get("truthStatus"),
                "execution_claim": source.get("executionMode"),
            }
        )
    return out


def render_state_html(snapshot: dict | None = None) -> str:
    """Render the offline snapshot with an unconditional unverified banner."""

    snapshot = state() if snapshot is None else snapshot
    cards = []
    for system in snapshot.get("systems", []):
        cards.append(
            "<li><strong>{}</strong> -- <span>{}</span>"
            "<small> source claim: {}</small></li>".format(
                html.escape(str(system.get("name", ""))),
                UNSIGNED_TRUTH,
                html.escape(str(system.get("source_truth_claim", ""))),
            )
        )
    return (
        "<!doctype html><meta charset='utf-8'><title>Cockpit v1 disabled</title>"
        "<h1>Operator Cockpit v1 -- HTTP DISABLED</h1>"
        "<p><strong>UNVERIFIED/PROPOSED</strong>: unsigned JSON metadata only.</p>"
        "<ul>" + "".join(cards) + "</ul>"
    )


def main() -> int:
    print(HTTP_DISABLED_REASON, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
