"""VERITAS seller backend tests. Run from backend/: python -m unittest discover -s tests -t ."""

import os
import sys
import tempfile

# Isolate every test run in its own database and a known seller token before app modules load.
os.environ.setdefault("VERITAS_DB_PATH", os.path.join(tempfile.mkdtemp(prefix="veritas-test-"), "jobs.db"))
os.environ.setdefault("HIRECREW_SELLER_TOKEN", "test-seller-token-0123456789abcdef")
os.environ.setdefault("VERITAS_ENV", "test")

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)
sys.path.append(os.path.dirname(_BACKEND))  # repo root, for the `agent` package
