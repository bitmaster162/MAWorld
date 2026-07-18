import os
import shutil
import sys
import tempfile

from external_effect_registry import (
    ExternalEffectRegistry,
    LegacyEffectRegistryDisabled,
)
from side_effect_adapters import (
    AdapterRegistry,
    FilesystemAdapter,
    LEGACY_DISABLED_REASON,
    LegacySideEffectDisabled,
    NetworkAdapter,
)


state = tempfile.mkdtemp()
out = os.path.join(state, "out")
os.makedirs(out)
db_path = os.path.join(state, "effects.db")
audit = []
registry = AdapterRegistry(db_path, audit_fn=lambda kind, payload: audit.append((kind, payload)))
filesystem = FilesystemAdapter(root=out)
network = NetworkAdapter(allowlist={"api.testnet.local"})
registry.register(filesystem)
registry.register(network)

results = {}
file_path = os.path.join(out, "must-not-exist.txt")
fs_spec = {
    "tool": "filesystem",
    "operation": "write_file",
    "idempotency_key": "attacker-controlled",
    "target": {"path": file_path, "content": "unsafe"},
}

# Knowing the historical capability string grants nothing and creates no file/DB.
denied = registry.execute(fs_spec, "fs.write")
results["bare fs capability fails closed"] = (
    denied.decision == "HOLD"
    and denied.reason == LEGACY_DISABLED_REASON
    and not os.path.exists(file_path)
    and not os.path.exists(db_path)
)

# Different credential-shaped inputs cannot revive the retired API.
for label, credential in (
    ("missing capability fails closed", None),
    ("object capability fails closed", {"scope": "fs.write", "signed": True}),
    ("bare network capability fails closed", "net.egress"),
):
    spec = fs_spec if "network" not in label else {
        "tool": "network",
        "operation": "http_post",
        "target": {"host": "api.testnet.local"},
    }
    result = registry.execute(spec, credential)
    results[label] = result.decision == "HOLD" and result.reason == LEGACY_DISABLED_REASON

# Direct adapter calls and rollback/compensation cannot bypass the registry.
try:
    filesystem._perform(fs_spec)
    direct_fs_denied = False
except LegacySideEffectDisabled:
    direct_fs_denied = True
results["direct filesystem perform denied"] = direct_fs_denied and not os.path.exists(file_path)

try:
    network._perform({"target": {"host": "api.testnet.local"}})
    direct_net_denied = False
except LegacySideEffectDisabled:
    direct_net_denied = True
results["direct network perform denied"] = direct_net_denied

existing = os.path.join(out, "existing.txt")
with open(existing, "w", encoding="utf-8") as handle:
    handle.write("preserve")
rollback_result = filesystem.rollback(
    {"target": {"path": existing}}, {"path": existing}
)
results["legacy rollback cannot delete"] = (
    rollback_result == LEGACY_DISABLED_REASON and os.path.exists(existing)
)

# Even the local crash-unsafe registry duplicate is a tombstone and opens no DB.
legacy_registry = ExternalEffectRegistry(db_path)
try:
    legacy_registry.execute_once("effect", lambda: {"unsafe": True})
    legacy_registry_denied = False
except LegacyEffectRegistryDisabled:
    legacy_registry_denied = True
results["legacy effect registry denied"] = legacy_registry_denied and not os.path.exists(db_path)

# Disabled execution does not invoke caller-controlled callbacks.
results["audit callback not invoked"] = audit == []

print("== Side-Effect Adapters legacy lockdown ==")
ok = True
for name, passed in results.items():
    print(("PASS" if passed else "FAIL"), "|", name)
    ok = ok and passed
print("\n" + (f"ALL PASS ({sum(results.values())}/{len(results)})" if ok else "FAIL"))

registry.close()
legacy_registry.close()
shutil.rmtree(state, ignore_errors=True)
sys.exit(0 if ok else 1)
