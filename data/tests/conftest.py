"""Data tests that touch the API adapters import the product backend (backend/app) as `app`."""
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.append(str(_BACKEND))
