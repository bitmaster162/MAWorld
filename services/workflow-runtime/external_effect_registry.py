"""Compatibility surface for the canonical hardened effect registry.

The former service-local implementation is intentionally gone: its legacy
``execute_once(effect_id, callback)`` API did not bind the idempotency key to a
tenant, action, or payload and could re-fire work left in ``SENT`` after a crash.
Callers must now provide the canonical registry's explicit binding arguments.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../libs")))

from maworld_core.hardened_effect_registry import (  # noqa: E402,F401
    HardenedEffectRegistry,
    IdempotencyBindingConflict,
    binding_digest,
)

ExternalEffectRegistry = HardenedEffectRegistry

__all__ = [
    "ExternalEffectRegistry",
    "HardenedEffectRegistry",
    "IdempotencyBindingConflict",
    "binding_digest",
]
