"""Delivery CLI exercises the real local API across a server restart, without providers."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def test_delivery_smoke_preserves_real_saved_card_and_session_across_restart(tmp_path):
    dist = tmp_path / "ui"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text('<!doctype html><html><script type="module" src="/assets/app.js"></script><body>Delivery UI</body></html>')
    (dist / "assets/app.js").write_text('document.body.dataset.loaded = "true";')
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    env = {**os.environ, "LLM_ENABLED": "false", "LLM_WARMUP_ENABLED": "false", "EMBED_MODEL": "off", "WEATHER_ENABLED": "false",
           "OPENAI_API_KEY": "", "LLM_API_KEY": "", "SMTP_HOST": "", "SMTP_FROM": "", "READINESS_PROFILE": "template",
           "DATABASE_URL": f"sqlite:///{tmp_path / 'accounts.db'}", "FRONTEND_DIST": str(dist), "SECRET_KEY": "delivery-test-only"}
    state = tmp_path / "smoke-state.json"
    server = None
    with (tmp_path / "server.log").open("w") as log:
        try:
            def start():
                proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--app-dir", "backend", "--host", "127.0.0.1", "--port", str(port)],
                                        cwd=ROOT, env=env, stdout=log, stderr=log)
                for _ in range(200):
                    assert proc.poll() is None, "Local delivery server exited"
                    try:
                        with urllib.request.urlopen(base + "/api/health", timeout=1) as response:
                            if response.status == 200:
                                return proc
                    except (OSError, urllib.error.URLError):
                        time.sleep(.1)
                proc.terminate()
                raise AssertionError("Local delivery server did not become ready")
            server = start()
            command = [sys.executable, "scripts/smoke_runtime.py", "--base-url", base, "--state", str(state)]
            initial = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=60)
            assert initial.returncode == 0, initial.stdout + initial.stderr
            saved_state = json.loads(state.read_text())
            assert saved_state["cookie"] not in initial.stdout + initial.stderr
            assert state.stat().st_mode & 0o777 == 0o600
            assert not saved_state["poi_id"].startswith(("test:", "idea-"))
            assert json.loads(initial.stdout)["phase"] == "initial"
            server.terminate()
            server.wait(timeout=10)
            server = start()
            resumed = subprocess.run(command + ["--resume"], cwd=ROOT, capture_output=True, text=True, timeout=60)
            assert resumed.returncode == 0, resumed.stdout + resumed.stderr
            assert json.loads(resumed.stdout)["phase"] == "resumed"
            assert saved_state["cookie"] not in resumed.stdout + resumed.stderr
            assert not state.exists(), "Revoked session state must be removed"
        finally:
            if server is not None:
                server.terminate()
                server.wait(timeout=10)


def test_delivery_smoke_refuses_cookie_state_inside_repository():
    command = [sys.executable, "scripts/smoke_runtime.py", "--base-url", "http://127.0.0.1:1", "--state", str(ROOT / ".delivery-secret.json")]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert "outside" in result.stderr.lower()
    assert not (ROOT / ".delivery-secret.json").exists()
