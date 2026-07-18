"""Deterministic test suite for the MCP 2025-11-25 normalizer."""
from mcp_preflight import normalize_mcp

def base(**over):
    m = {"headers": {"mcp-protocol-version": "2025-11-25", "origin": "https://localhost"},
         "transport": "streamable_http", "allowed_origins": ["https://localhost"],
         "oauth": {"resource_server_uri": "https://tool.local", "token_audience": "https://tool.local"},
         "task": {"state": "none"}}
    m.update(over); return m

cases = []
def check(name, meta, expect_decision, expect_reason_substr=None):
    r = normalize_mcp(meta)
    ok = r.decision == expect_decision
    if expect_reason_substr:
        ok = ok and any(expect_reason_substr in x for x in r.reasons)
    cases.append((name, ok, r.decision, r.reasons))

# happy path
check("valid 2025-11-25 request", base(), "ALLOW")
# version gating
check("RC 2026-07-28 -> HOLD", base(headers={"mcp-protocol-version":"2026-07-28","origin":"https://localhost"}), "HOLD", "release-candidate")
check("missing version -> HOLD", base(headers={"origin":"https://localhost"}), "HOLD", "missing MCP-Protocol-Version")
check("unknown version -> HOLD", base(headers={"mcp-protocol-version":"9999-99-99","origin":"https://localhost"}), "HOLD", "unsupported")
# spoofed header
check("unknown MCP header -> DENY", base(headers={"mcp-protocol-version":"2025-11-25","origin":"https://localhost","mcp-evil":"x"}), "DENY", "unknown MCP header")
# origin
check("missing origin -> DENY", base(headers={"mcp-protocol-version":"2025-11-25"}), "DENY", "Origin")
check("bad origin -> DENY", base(headers={"mcp-protocol-version":"2025-11-25","origin":"https://evil.com"}), "DENY", "Origin")
# oauth
check("token passthrough -> DENY", base(oauth={"resource_server_uri":"https://tool.local","token_audience":"https://tool.local","operator_bearer_forwarded":True}), "DENY", "passthrough")
check("audience mismatch -> DENY", base(oauth={"resource_server_uri":"https://tool.local","token_audience":"https://other.local"}), "DENY", "audience mismatch")
check("scope challenge -> HOLD", base(oauth={"resource_server_uri":"https://tool.local","token_audience":"https://tool.local","scope_challenge":True}), "HOLD", "incremental scope")
# tasks
check("task created != complete -> HOLD", base(task={"state":"created","id":"t1"}), "HOLD", "not completion")

print("== MCP normalizer tests ==")
passed = 0
for name, ok, dec, reasons in cases:
    print(("PASS" if ok else "FAIL"), f"| {name:38s} -> {dec}")
    passed += ok
print(f"\n{passed}/{len(cases)} passed")
import sys; sys.exit(0 if passed==len(cases) else 1)
