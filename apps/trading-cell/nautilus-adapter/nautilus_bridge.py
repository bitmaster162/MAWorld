import os
import sys

sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../libs")),
)

from maworld_core.nautilus_bridge import *  # canonical proposal-only risk seam
