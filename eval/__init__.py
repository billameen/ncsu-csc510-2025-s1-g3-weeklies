"""Offline evaluation of the Weeklies meal planner."""

import os
import sys

# The app's modules (sqlQueries, pricing, menu_generation, ...) import each other as top-level
# modules, so app/ has to be on the path when the eval runs from the repo root.
_APP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
if _APP_DIR not in sys.path:
    sys.path.append(_APP_DIR)
