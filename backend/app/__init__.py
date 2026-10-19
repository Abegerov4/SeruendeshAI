"""SeruendeshAI API package.

The team's catalogue helpers live in the repository-level `data` package (Aslan): meal-cost evidence,
eligibility, city services and versioned snapshots; `runtime_support` holds the provider health probe. Expose it when the package sits next to backend/
(the repository root locally, /srv in the Docker image)."""
import sys as _sys
from pathlib import Path as _Path

_ROOT = _Path(__file__).resolve().parents[2]
if (_ROOT / "data" / "__init__.py").exists() and str(_ROOT) not in _sys.path:
    _sys.path.append(str(_ROOT))
