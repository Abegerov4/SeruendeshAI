"""Load backend/eval/run_eval.py by path: the repository root also has a team `eval` package (QA, Aslan)."""
import importlib.util
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location("backend_scenario_eval", Path(__file__).resolve().parents[1] / "eval" / "run_eval.py")
run_eval = importlib.util.module_from_spec(_spec)
sys.modules["backend_scenario_eval"] = run_eval
_spec.loader.exec_module(run_eval)
