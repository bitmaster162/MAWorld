"""DLP redaction — scrub secrets/PII from ANY payload before an external effect or a log line.
Pattern-based (API keys, bearer/JWT, emails, PAN) + exact-match against known secret values."""
import re

_PATTERNS = [
    ("API_KEY", re.compile(r"\b(sk|pk|rk)_[A-Za-z0-9_]{12,}\b")),
    ("AWS_KEY", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("BEARER",  re.compile(r"\bBearer\s+[A-Za-z0-9\.\-_]{16,}\b")),
    ("JWT",     re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b")),
    ("EMAIL",   re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
    ("PAN",     re.compile(r"\b(?:\d[ -]*?){13,19}\b")),
]

def redact_text(s: str, known_secrets=()) -> str:
    for val in known_secrets:
        if val:
            s = s.replace(val, "[REDACTED:SECRET]")
    for name, rx in _PATTERNS:
        s = rx.sub(f"[REDACTED:{name}]", s)
    return s

def redact(obj, known_secrets=()):
    if isinstance(obj, str): return redact_text(obj, known_secrets)
    if isinstance(obj, dict): return {k: redact(v, known_secrets) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)): return type(obj)(redact(v, known_secrets) for v in obj)
    return obj

def leak_detected(obj, known_secrets) -> bool:
    """True if any known secret value appears verbatim anywhere in the payload."""
    import json
    blob = json.dumps(obj, default=str)
    return any(v and v in blob for v in known_secrets)
