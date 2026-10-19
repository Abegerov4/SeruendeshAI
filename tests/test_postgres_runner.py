"""Explicit Docker verification of the delivery database runner and its cleanup."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_disposable_postgres_runner_verifies_accounts_and_removes_its_container():
    if os.environ.get("DELIVERY_DOCKER_VERIFY") != "1":
        pytest.skip("Set DELIVERY_DOCKER_VERIFY=1 for the disposable Docker PostgreSQL run")
    result = subprocess.run([sys.executable, "scripts/test_delivery_postgres.py"], cwd=ROOT, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
    summary = json.loads(result.stdout.strip().splitlines()[-1])
    assert summary["ok"] and summary["container_removed"]
    assert summary["postgres_image"].startswith("postgres:")
    assert "5 passed" in result.stdout
    leftover = subprocess.run(["docker", "ps", "-aq", "--filter", "name=" + summary["container"]], capture_output=True, text=True, check=True)
    assert not leftover.stdout.strip()
