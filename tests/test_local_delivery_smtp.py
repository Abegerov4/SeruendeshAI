"""Reset delivery must use an actual localhost SMTP STARTTLS connection."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def test_real_local_smtp_reset_roundtrip_and_disabled_503():
    result = subprocess.run([sys.executable, "scripts/check_local_smtp.py"], cwd=ROOT, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    summary = json.loads(result.stdout)
    assert summary == {"ok": True, "smtp_transport": "localhost-starttls", "captured_messages": 1,
                       "reset_reuse_rejected": True, "prior_session_revoked": True,
                       "logout_replay_rejected": True, "smtp_disabled_status": 503}
    assert "token=" not in result.stdout and "seru_session=" not in result.stdout
