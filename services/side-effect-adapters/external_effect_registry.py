"""Fail-closed tombstone for the retired, crash-unsafe effect registry.

Use ``maworld_core.hardened_effect_registry.HardenedEffectRegistry`` instead.
The old implementation could re-fire work after a crash between SENT and
CONFIRMED.  Keeping an executable compatibility copy would recreate that risk.
"""
from __future__ import annotations


LEGACY_DISABLED_REASON = (
    "LEGACY_EFFECT_REGISTRY_DISABLED_USE_"
    "MAWORLD_CORE_HARDENED_EFFECT_REGISTRY"
)


class LegacyEffectRegistryDisabled(RuntimeError):
    pass


class ExternalEffectRegistry:
    """Import-compatible class whose effect-bearing operations all reject."""

    def __init__(self, path):
        # Deliberately do not open or create ``path``.
        self.path = None

    @staticmethod
    def _disabled(*args, **kwargs):
        raise LegacyEffectRegistryDisabled(LEGACY_DISABLED_REASON)

    register_intent = _disabled
    execute_once = _disabled
    reconcile = _disabled
    compensate = _disabled

    def status(self, effect_id):
        raise LegacyEffectRegistryDisabled(LEGACY_DISABLED_REASON)

    def close(self):
        return None
