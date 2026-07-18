"""Compatibility import for the canonical verifier-only secrets broker."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../libs")))

from maworld_core.secrets_broker import *
