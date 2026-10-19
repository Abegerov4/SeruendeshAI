#!/usr/bin/env python3
"""Run local account/migration/concurrency checks in an owned disposable PostgreSQL.

Uses a unique container, random localhost port, RAM-only database and random test
password. Removes only its own container, including on test failures. No SMTP or
model provider is invoked. Requires Docker and the integration Python environment.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def docker(*args, check=True):
    return subprocess.run(["docker", *args], check=check, capture_output=True, text=True)


def run(image):
    name = "seru-delivery-pg-" + secrets.token_hex(6)
    password = secrets.token_urlsafe(32)
    created = False
    completed = None
    removed = False
    image_id = None
    try:
        docker("info", "--format", "{{.ServerVersion}}")
        docker("run", "--rm", "-d", "--name", name, "--publish", "127.0.0.1::5432",
               "--tmpfs", "/var/lib/postgresql/data", "--env", "POSTGRES_USER=delivery",
               "--env", "POSTGRES_DB=delivery", "--env", "POSTGRES_PASSWORD=" + password, image)
        created = True
        image_id = docker("inspect", "--format", "{{.Image}}", name).stdout.strip()
        for _ in range(60):
            if docker("exec", name, "pg_isready", "-U", "delivery", "-d", "delivery", check=False).returncode == 0:
                break
            time.sleep(.5)
        else:
            raise RuntimeError("Disposable PostgreSQL did not become ready")
        binding = docker("port", name, "5432/tcp").stdout.strip()
        port = int(binding.rsplit(":", 1)[1])
        env = {**os.environ, "DELIVERY_POSTGRES_URL": f"postgresql://delivery:{password}@127.0.0.1:{port}/delivery",
               "LLM_ENABLED": "false", "WEATHER_ENABLED": "false", "EMBED_MODEL": "off",
               "OPENAI_API_KEY": "", "LLM_API_KEY": "", "SMTP_HOST": "", "SMTP_FROM": ""}
        completed = subprocess.run([sys.executable, "-m", "pytest", "tests/test_postgres_delivery.py", "-q"],
                                   cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
        # SQL-driver exceptions may include a DSN: scrub the random credential before output.
        print(completed.stdout.replace(password, "[redacted]"), end="")
        if completed.stderr:
            print(completed.stderr.replace(password, "[redacted]"), file=sys.stderr, end="")
    finally:
        if created:
            removed = docker("rm", "--force", "--volumes", name, check=False).returncode == 0
            removed = removed and not docker("ps", "-aq", "--filter", "name=" + name).stdout.strip()
    summary = {"ok": completed is not None and completed.returncode == 0 and removed, "container": name,
               "container_removed": bool(removed), "postgres_image": image, "image_id": image_id}
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["ok"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="postgres:17-alpine")
    args = parser.parse_args()
    try:
        return run(args.image)
    except (OSError, subprocess.SubprocessError, RuntimeError, ValueError) as error:
        print(f"PostgreSQL delivery check failed ({type(error).__name__}); owned-container cleanup attempted", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
