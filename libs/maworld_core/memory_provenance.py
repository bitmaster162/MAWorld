"""Memory provenance guard (OWASP Agentic 2026: memory/context poisoning). Every memory item carries
provenance (source, trust, ts) + HMAC. Retrieval returns only items above a trust floor AND signed;
instruction-like content from an untrusted source is quarantined (a 'belief it should never have learned')."""
from __future__ import annotations
import hashlib, hmac, json, math, re, time

_INSTRUCTION_LIKE = re.compile(r"(always|never|from now on|ignore|you must|forward .* to|send .* to)", re.I)


def _canonical(body: dict) -> bytes:
    return json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _sign_body(key: bytes, body: dict) -> str:
    if not isinstance(key, bytes) or not key:
        raise ValueError("non-empty bytes provenance key required")
    return hmac.new(key, _canonical(body), hashlib.sha256).hexdigest()


def _valid_body(body: dict) -> bool:
    trust = body.get("trust")
    return (
        isinstance(body.get("text"), str)
        and isinstance(body.get("source"), str)
        and not isinstance(trust, bool)
        and isinstance(trust, (int, float))
        and math.isfinite(float(trust))
        and 0.0 <= float(trust) <= 1.0
        and not isinstance(body.get("ts"), bool)
        and isinstance(body.get("ts"), int)
    )


def sign_item(key: bytes, text: str, source: str, trust: float, ts: float, *, provenance=None) -> str:
    """Sign the complete memory envelope, including optional provenance claims."""
    body = {"text": text, "source": source, "trust": trust, "ts": int(ts)}
    if provenance is not None:
        if not isinstance(provenance, dict) or any(k in body or k == "sig" for k in provenance):
            raise ValueError("provenance must not override authenticated envelope fields")
        body.update(provenance)
    if not _valid_body(body):
        raise ValueError("invalid memory provenance envelope")
    return _sign_body(key, body)


def make_item(key: bytes, text: str, source: str, trust: float, ts=None, *, provenance=None):
    ts = time.time() if ts is None else ts
    body = {"text": text, "source": source, "trust": trust, "ts": int(ts)}
    if provenance is not None:
        if not isinstance(provenance, dict) or any(k in body or k == "sig" for k in provenance):
            raise ValueError("provenance must not override authenticated envelope fields")
        body.update(provenance)
    if not _valid_body(body):
        raise ValueError("invalid memory provenance envelope")
    return {**body, "sig": _sign_body(key, body)}


def verify_item(key: bytes, item: dict) -> bool:
    try:
        if not isinstance(item, dict):
            return False
        signature = item.get("sig")
        if not isinstance(signature, str) or len(signature) != 64:
            return False
        body = {name: value for name, value in item.items() if name != "sig"}
        if not _valid_body(body):
            return False
        return hmac.compare_digest(signature, _sign_body(key, body))
    except (TypeError, ValueError, OverflowError):
        return False

def is_poisoned(item: dict) -> bool:
    """Instruction-like content from a low-trust source = poisoning attempt."""
    return bool(_INSTRUCTION_LIKE.search(item.get("text",""))) and float(item.get("trust",0)) < 0.9

def retrieve(key: bytes, items, trust_floor=0.5):
    """Return only signed, trusted, non-poisoned items; quarantine the rest."""
    safe, quarantined = [], []
    for it in items:
        if not verify_item(key, it): quarantined.append((it, "unsigned/tampered")); continue
        if float(it["trust"]) < trust_floor: quarantined.append((it, "below trust floor")); continue
        if is_poisoned(it): quarantined.append((it, "poisoning: instruction from low-trust")); continue
        safe.append(it)
    return {"safe": safe, "quarantined": quarantined}
