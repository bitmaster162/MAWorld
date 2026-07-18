"""Compatibility import for the canonical, payload-bound effect registry."""
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
