import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../libs")))
from maworld_core.hardened_effect_registry import *  # SHIM -> libs/maworld_core (single source of truth)
