"""Compatibility import for the canonical, payload-bound effect registry.

This legacy Trading Cell adapter is paper-only.  Keeping the import local avoids
breaking the old demo while ensuring it cannot fall back to the former registry
that could re-fire a ``SENT`` effect after a crash.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../libs")))

from maworld_core.hardened_effect_registry import (  # noqa: E402,F401
    HardenedEffectRegistry as ExternalEffectRegistry,
    IdempotencyBindingConflict,
    binding_digest,
)

__all__ = ["ExternalEffectRegistry", "IdempotencyBindingConflict", "binding_digest"]
