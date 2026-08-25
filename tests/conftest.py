"""Pytest path setup for the unit tests.

Puts ``src`` on ``sys.path`` so tests can ``import regex_fandango_transpiler`` /
``import pipeline.config`` / ``import paths`` the same way the pipeline modules
import each other (they run with ``src`` as an entry on the path). Mirrors the
smoke tests, which ``cd`` into a copied tree; here we just prepend ``src``.
"""

import os
import sys

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
