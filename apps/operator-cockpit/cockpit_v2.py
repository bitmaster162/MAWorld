"""Operator Cockpit v2 offline renderer -- HTTP hard-disabled.

All manifest, acceptance, and PFI files are unsigned proposal metadata.  An
``accepted: true`` value is never interpreted as Evidence Engine acceptance.
Network serving remains disabled until fixed ActionVerifier and
EvidenceAcceptor dependencies are wired at the application boundary.
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
PFI_FEED = os.environ.get(
    "PFI_FEED", os.path.abspath(os.path.join(HERE, "..", "pfi-intake", "pfi_feed.json"))
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
    """Build a fail-closed offline snapshot from unsigned source files."""

    out = {
        "systems": [],
        "errors": [],
        "pfi": None,
        "http": "DISABLED",
        "verification": "UNAVAILABLE",
    }
    acceptances = _acceptance_index(
        _load(ACCEPT, {}, out["errors"], "unsigned acceptances")
    )
    manifest = _load(MANIFEST, {}, out["errors"], "unsigned manifest")
    if not isinstance(manifest, dict):
        out["errors"].append("unsigned manifest: object required")
        manifest = {}

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

    feed = _load(PFI_FEED, None, out["errors"], "unsigned PFI feed")
    if isinstance(feed, dict):
        items = []
        for item in feed.get("items", [])[:15]:
            if not isinstance(item, dict):
                continue
            sources = item.get("sources") or [""]
            items.append(
                {
                    "status": "PROPOSED",
                    "text": item.get("text", ""),
                    "confidence_claim": item.get("confidence"),
                    "source_claim": sources[0] if isinstance(sources, list) and sources else "",
                }
            )
        out["pfi"] = {
            "status": "PROPOSED",
            "proposed_claim": feed.get("proposed"),
            "actions_claim": feed.get("actions"),
            "rejected_claim": feed.get("rejected_injection"),
            "items": items,
        }
    return out


def render_state_html(snapshot: dict | None = None) -> str:
    """Render unsigned state without any VERIFIED presentation state."""

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
        "<!doctype html><meta charset='utf-8'><title>Cockpit v2 disabled</title>"
        "<h1>Operator Cockpit v2 -- HTTP DISABLED</h1>"
        "<p><strong>UNVERIFIED/PROPOSED</strong>: unsigned JSON and PFI proposals only.</p>"
        "<ul>" + "".join(cards) + "</ul>"
    )


def main() -> int:
    print(HTTP_DISABLED_REASON, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
