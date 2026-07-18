"""Multimodal input guard — from PFI signal 'Ghostcommit' (prompt injection hidden in a PNG referenced by
AGENTS.md; agent reads it, grabs .env, writes secrets). Treat images/PDF/config/AGENTS.md as an UNTRUSTED
EXECUTABLE SURFACE: extract embedded strings and injection-scan them; forbid agent reads of secret files;
require confirmation before secret export / CI change."""
from __future__ import annotations
import os, re
from maworld_core.input_guard import scan

EXECUTABLE_SURFACES = {".png",".jpg",".jpeg",".gif",".webp",".pdf",".svg",".yaml",".yml",".toml",".ini",".md"}
SECRET_FILES = re.compile(r"(^|/)\.env(\.|$)|/secrets?/|\.pem$|\.key$|id_rsa|credentials", re.I)
HIGH_IMPACT = re.compile(r"(export .*secret|\.env|ci[/_-]?cd|\.github/workflows|deploy key|rotate)", re.I)

def is_executable_surface(name: str) -> bool:
    return os.path.splitext(name)[1].lower() in EXECUTABLE_SURFACES

def scan_embedded(name: str, data: bytes):
    """Extract printable strings from a binary/config and injection-scan them (multimodal review)."""
    text = re.sub(rb"[^\x20-\x7e\n]+", b" ", data or b"").decode("ascii","ignore")
    s = scan(text)
    return {"file": name, "executable_surface": is_executable_surface(name),
            "injection": s["injection"], "markers": s["markers"]}

def guard_agent_file_read(path: str):
    """Agents may NOT read secret files (Ghostcommit exfil step)."""
    if SECRET_FILES.search(path):
        return {"allow": False, "reason": "agent read of secret file forbidden (.env/keys)"}
    return {"allow": True}

def requires_confirmation(action_text: str) -> bool:
    return bool(HIGH_IMPACT.search(action_text or ""))
