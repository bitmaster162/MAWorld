"""PFI bridge — connect ContinuityOS PFI (frontier intelligence) to MAWorld through the UNTRUSTED-input
pipeline. PFI signals are external intel (the digest itself warns about Ghostcommit image-injection), so
EVERY signal passes input_guard (prompt-injection) + memory_provenance (trust-scored, provenance-tagged).

Invariants:
  * Signal != verified fact. Signals land as PROPOSED memory (Governed Memory), never canon.
  * A signal's 'practical action' that would touch MAWorld becomes a gated PROPOSAL (authoritative=False),
    never auto-applied.
  * Provenance (sources, confidence) preserved; injected instructions quarantined.
Two inputs: parse_digest(text) for a pasted GPT digest (manual now) OR from_frontier_rows(rows) for the
real reflex/pfi FrontierStore (auto later — same downstream)."""
from __future__ import annotations
import math
import re
from maworld_core.input_guard import admit_input, scan
from maworld_core.memory_provenance import make_item, retrieve

_CONF = {"высок": 0.55, "средне-высок": 0.45, "средн": 0.4, "низк": 0.25}
PFI_TRUST = 0.5   # 'tool'-grade: intel, not owner truth -> cannot carry instructions into memory
MAX_DIGEST_BYTES = 4 * 1024 * 1024
MAX_SIGNALS = 1000
MAX_FIELD_CHARS = 4096
MAX_SOURCE_CHARS = 2048
MAX_SOURCES = 20


def _bounded_text(value, limit=MAX_FIELD_CHARS):
    if not isinstance(value, str):
        raise ValueError("PFI text fields must be strings")
    if len(value) > limit:
        raise ValueError("PFI text field exceeds limit")
    return value


def _sanitize_signal(value):
    if not isinstance(value, dict):
        raise ValueError("PFI signal must be an object")
    confidence = value.get("confidence", 0.3)
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ValueError("PFI confidence must be numeric")
    confidence = float(confidence)
    if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        raise ValueError("PFI confidence must be finite and in [0,1]")
    raw_sources = value.get("sources", [])
    if not isinstance(raw_sources, list) or len(raw_sources) > MAX_SOURCES:
        raise ValueError("PFI sources must be a bounded list")
    sources = []
    for source in raw_sources:
        source = _bounded_text(source, MAX_SOURCE_CHARS)
        if source and not source.startswith(("https://", "http://")):
            raise ValueError("PFI source URL scheme is not allowed")
        if source:
            sources.append(source)
    return {
        "title": _bounded_text(value.get("title", "")),
        "what": _bounded_text(value.get("what", "")),
        "why": _bounded_text(value.get("why", "")),
        "action": _bounded_text(value.get("action", "")),
        "confidence": confidence,
        "sources": sources,
        "domain": _bounded_text(value.get("domain", "frontier"), 256),
    }

def _confidence(text: str) -> float:
    t = (text or "").lower()
    for k, v in _CONF.items():
        if k in t: return v
    return 0.3

def parse_digest(text: str) -> list:
    """Parse the GPT PFI digest (## N. Title + Что произошло/Почему важно/Практическое действие/Уверенность
    + source URLs). Robust to the RU template."""
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_DIGEST_BYTES:
        raise ValueError("PFI digest must be bounded UTF-8 text")
    signals = []
    # reference-style links: footer '[1]: https://...' -> resolve per-signal '[1]' citations
    ref_map = dict(re.findall(r"(?m)^\[(\d+)\]:\s*(https?://\S+)", text))
    blocks = re.split(r"\n##\s+\d+\.\s+", "\n" + text)
    for b in blocks[1:MAX_SIGNALS + 1]:
        title = b.split("\n", 1)[0].strip()
        def _field(label):
            m = re.search(rf"\*\*{label}[^*]*\*\*[:.]?\s*(.+?)(?=\n\s*\n|\n\*\*|\Z)", b, re.S)
            return (m.group(1).strip() if m else "")
        what = _field("Что произошло")
        why = _field("Почему важно")
        action = _field("Практическ")   # Практическое действие / Практический вывод
        conf = _confidence(_field("Уверенность"))
        inline = re.findall(r"https?://[^\s)\]]+", b)
        cited = [ref_map[n] for n in re.findall(r"\]\[(\d+)\]", b) if n in ref_map]
        sources = list(dict.fromkeys(inline + cited))   # dedup, keep order
        try:
            signals.append(_sanitize_signal({
                "title": title, "what": what, "why": why, "action": action,
                "confidence": conf, "sources": sources, "domain": "frontier",
            }))
        except ValueError:
            continue
    return signals

def from_frontier_rows(rows: list) -> list:
    """Adapt the real FrontierStore rows (reflex/pfi): {title, decision, domain, source, confidence,...}."""
    if not isinstance(rows, list):
        return []
    out = []
    for r in rows[:MAX_SIGNALS]:
        if not isinstance(r, dict):
            continue
        try:
            out.append(_sanitize_signal({
                "title": r.get("title", ""),
                "what": r.get("description", r.get("what", "")),
                "why": r.get("why", ""),
                "action": r.get("action", ""),
                "confidence": r.get("confidence", 0.3),
                "sources": [r["source"]] if r.get("source") else [],
                "domain": r.get("domain", "frontier"),
            }))
        except ValueError:
            continue
    return out

def ingest(signals: list, mem_key: bytes, source_label="pfi:frontier"):
    """Run signals through the untrusted-input pipeline. Returns PROPOSED memory + quarantined + gated
    action-proposals. Nothing is canon; nothing is executed."""
    if not isinstance(signals, list):
        raise ValueError("signals must be a list")
    if not isinstance(mem_key, bytes) or len(mem_key) < 16:
        raise ValueError("explicit provenance key of at least 16 bytes is required")
    source_label = _bounded_text(source_label, 256)
    proposed_items, quarantined, action_proposals, rejected = [], [], [], []
    for raw in signals[:MAX_SIGNALS]:
        try:
            s = _sanitize_signal(raw)
        except ValueError as error:
            rejected.append({"title": "", "reason": str(error)})
            continue
        blob = " ".join([s.get("title",""), s.get("what",""), s.get("why",""), s.get("action","")])
        # 1) prompt-injection guard (external intel is untrusted)
        adm = admit_input(blob, source="tool", high_impact=False)
        if not adm["admit"]:
            rejected.append({"title": s["title"], "reason": adm["reason"]}); continue
        # 2) provenance-tagged, trust-scored memory item (signal, not fact)
        item = make_item(
            mem_key,
            s["title"] + " :: " + s.get("what", ""),
            source_label,
            PFI_TRUST,
            provenance={
                "provenance_schema": "maworld.pfi.signal.v1",
                "classification": "PROPOSED_INTEL",
                "domain": s["domain"],
                "confidence": s["confidence"],
                "sources": s["sources"],
                "authoritative": False,
            },
        )
        proposed_items.append(item)
        # 3) if the signal proposes an action touching MAWorld -> gated PROPOSAL, never auto-applied
        if s.get("action"):
            action_proposals.append({"from_signal": s["title"], "action": s["action"][:200],
                                     "confidence": s["confidence"], "authoritative": False,
                                     "requires": ["policy_engine", "action_authority", "signed_human_confirmation"]})
    # 4) memory retrieval defense (quarantine any poisoning that slipped through as instruction-like)
    r = retrieve(mem_key, proposed_items, trust_floor=0.4)
    return {"proposed_memory": r["safe"], "quarantined": r["quarantined"] + [],
            "action_proposals": action_proposals, "rejected_injection": rejected,
            "note": "signals are PROPOSED intel (confidence-scored), NOT canon; actions are gated proposals"}
