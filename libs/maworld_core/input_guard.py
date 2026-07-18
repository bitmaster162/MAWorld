"""Input guard (OWASP Agentic 2026: prompt injection / goal hijacking). Treat every input as untrusted:
trust-score by source, detect injection markers, and require BOTH clean + trusted for goal-changing
(high-impact) actions."""
from __future__ import annotations
import re

_INJECTION = [re.compile(p, re.I) for p in [
    r"ignore\b[\w\s]{0,30}\b(instructions|prompt|rules)",
    r"disregard (the|all|previous|above)",
    r"you are now (a|an|the)?",
    r"system prompt", r"reveal (your |the )?(system )?(prompt|instructions)",
    r"forget (everything|all|previous)", r"new instructions:", r"</?(system|assistant)>",
    r"do anything now|DAN mode|developer mode",
    r"exfiltrate|send .* to (http|https|@)", r"print (your )?(api|secret|key|token)",
]]
SOURCE_TRUST = {"owner": 1.0, "internal": 0.7, "tool": 0.5, "external": 0.2, "unknown": 0.0}

def scan(text: str):
    hits = [rx.pattern for rx in _INJECTION if rx.search(text or "")]
    return {"injection": bool(hits), "markers": hits}

def trust(source: str) -> float:
    return SOURCE_TRUST.get(source, 0.0)

def admit_input(text: str, source: str, high_impact=False, min_trust=0.7):
    s = scan(text); t = trust(source)
    if s["injection"]:
        return {"admit": False, "reason": "prompt-injection markers", "markers": s["markers"]}
    if high_impact and t < min_trust:
        return {"admit": False, "reason": f"high-impact needs trust>={min_trust}, source '{source}'={t}"}
    return {"admit": True, "trust": t}
