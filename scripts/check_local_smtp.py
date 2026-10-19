#!/usr/bin/env python3
"""Exercise real localhost STARTTLS/reset transport with temporary accounts only.

No external SMTP host is contacted. Certificate, private key, SQLite accounts and
mail contents live only in an automatically removed private temporary directory.
"""
from __future__ import annotations

from contextlib import contextmanager
from email import policy
from email.parser import BytesParser
import json
import os
from pathlib import Path
import queue
import re
import secrets
import socket
import socketserver
import ssl
import subprocess
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.smoke_runtime import Client, SmokeError, require, verify_logout, wait_ready


class CaptureSMTP(socketserver.StreamRequestHandler):
    def send(self, value):
        self.wfile.write(value + b"\r\n")
        self.wfile.flush()

    def handle(self):
        self.send(b"220 localhost delivery-test ESMTP")
        secured = False
        while True:
            line = self.rfile.readline(65536)
            if not line:
                break
            command = line.split(b" ", 1)[0].strip().upper()
            if command in {b"EHLO", b"HELO"}:
                if not secured:
                    self.send(b"250-localhost\r\n250 STARTTLS")
                else:
                    self.send(b"250 localhost")
            elif command == b"STARTTLS":
                self.send(b"220 Ready for TLS")
                self.connection = self.server.tls.wrap_socket(self.connection, server_side=True)
                self.rfile = self.connection.makefile("rb")
                self.wfile = self.connection.makefile("wb")
                secured = True
            elif command in {b"MAIL", b"RCPT", b"RSET", b"NOOP"}:
                self.send(b"250 OK")
            elif command == b"DATA":
                if not secured:
                    self.send(b"530 STARTTLS required")
                    continue
                self.send(b"354 End with <CRLF>.<CRLF>")
                lines = []
                while True:
                    part = self.rfile.readline(65536)
                    if part in {b".\r\n", b".\n", b""}:
                        break
                    lines.append(part[1:] if part.startswith(b"..") else part)
                self.server.messages.put(b"".join(lines))
                self.send(b"250 Accepted locally")
            elif command == b"QUIT":
                self.send(b"221 Bye")
                break
            else:
                self.send(b"502 Unsupported command")


@contextmanager
def smtp_capture(directory):
    key, cert = directory / "key.pem", directory / "certificate.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(cert),
                    "-subj", "/CN=localhost", "-days", "1"], check=True, capture_output=True)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), CaptureSMTP)
    server.daemon_threads = True
    server.tls, server.messages = context, queue.Queue()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@contextmanager
def local_runtime(directory, smtp_port=None):
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    env = {**os.environ, "LLM_ENABLED": "false", "LLM_WARMUP_ENABLED": "false", "EMBED_MODEL": "off", "WEATHER_ENABLED": "false",
           "OPENAI_API_KEY": "", "LLM_API_KEY": "", "SMTP_HOST": "127.0.0.1" if smtp_port else "",
           "SMTP_FROM": "delivery@example.com" if smtp_port else "", "SMTP_PORT": str(smtp_port or 587),
           "SMTP_USER": "", "SMTP_PASSWORD": "", "READINESS_PROFILE": "template", "PUBLIC_URL": base,
           "DATABASE_URL": f"sqlite:///{directory / 'accounts.db'}", "SECRET_KEY": "private-local-smtp-test"}
    with (directory / "runtime.log").open("a") as log:
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--app-dir", "backend", "--host", "127.0.0.1", "--port", str(port)],
                                   cwd=ROOT, env=env, stdout=log, stderr=log)
        try:
            client = Client(base)
            wait_ready(client, timeout=30)
            yield client
        finally:
            process.terminate()
            process.wait(timeout=10)


def run():
    with tempfile.TemporaryDirectory(prefix="seru-local-smtp-") as scratch:
        directory = Path(scratch)
        with smtp_capture(directory) as capture:
            email, password = f"smtp-{secrets.token_hex(8)}@example.com", secrets.token_urlsafe(24)
            with local_runtime(directory, capture.server_address[1]) as client:
                client.request("/api/auth/register", "POST", {"name": "Local SMTP", "email": email, "password": password}, expected=201)
                old = client.cookie
                client.request("/api/auth/password-reset/request", "POST", {"email": email}, expected=202)
                message = BytesParser(policy=policy.default).parsebytes(capture.messages.get(timeout=5))
                body = message.get_body(preferencelist=("plain",)).get_content()
                match = re.search(r"token=([A-Za-z0-9_-]+)", body)
                require(match is not None, "local reset email contained no confirmation token")
                require(str(message["To"]) == email, "local reset email addressed the wrong account")
                token, new_password = match.group(1), secrets.token_urlsafe(24)
                payload = {"token": token, "password": new_password}
                client.request("/api/auth/password-reset/confirm", "POST", payload)
                current = client.cookie
                revoked, _ = client.request("/api/auth/me", cookie=old)  # guests (incl. a revoked session) get 200 {"user": null}
                require(revoked == {"user": None}, "revoked session is still authenticated")
                client.cookie = current
                client.request("/api/auth/me")
                client.request("/api/auth/password-reset/confirm", "POST", payload, expected=400)
                verify_logout(client)
                client.request("/api/auth/login", "POST", {"email": email, "password": password}, expected=401)
                client.request("/api/auth/login", "POST", {"email": email, "password": new_password})
                verify_logout(client)
            with local_runtime(directory) as disabled:
                response, _ = disabled.request("/api/auth/password-reset/request", "POST", {"email": email}, expected=503)
                require(response == {"detail": "email_unavailable"}, "disabled SMTP returned the wrong public error")
            require(capture.messages.empty(), "disabled SMTP unexpectedly attempted another delivery")
    return {"ok": True, "smtp_transport": "localhost-starttls", "captured_messages": 1,
            "reset_reuse_rejected": True, "prior_session_revoked": True,
            "logout_replay_rejected": True, "smtp_disabled_status": 503}


if __name__ == "__main__":
    try:
        print(json.dumps(run(), sort_keys=True))
    except (SmokeError, OSError, ValueError, queue.Empty, subprocess.SubprocessError) as error:
        print(f"Local SMTP delivery check failed ({type(error).__name__}); private temporary state removed", file=sys.stderr)
        raise SystemExit(1)
