#!/usr/bin/env python3
"""Stdlib-only, same-origin delivery smoke with a restart-safe temporary state.

Initial run leaves one live session and one real saved recommendation. --resume
verifies both survived restart, revokes the session and removes the state file.
State is private (0600), must be outside the checkout, and is never printed.
"""
from __future__ import annotations

import argparse
from http.cookies import SimpleCookie
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request


class SmokeError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self, base_url, cookie=None):
        parts = urllib.parse.urlsplit(base_url)
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
            raise SmokeError("base URL must be an HTTP(S) origin without credentials")
        self.base = base_url.rstrip("/")
        self.cookie = cookie
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def request(self, path, method="GET", body=None, expected=200, *, cookie=None):
        if not path.startswith("/") or path.startswith("//"):
            raise SmokeError("smoke requests must remain on the selected origin")
        headers = {"Accept": "application/json"}
        value = self.cookie if cookie is None else cookie
        if value:
            if "\r" in value or "\n" in value:
                raise SmokeError("invalid session state")
            headers["Cookie"] = value
        data = json.dumps(body).encode() if body is not None else None
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            response = self.opener.open(request, timeout=15)
        except urllib.error.HTTPError as error:
            response = error
        except (OSError, urllib.error.URLError) as error:
            raise SmokeError(f"{method} {path.split('?')[0]} could not connect ({type(error).__name__})") from None
        with response:
            payload = response.read(4 * 1024 * 1024)
            content_type = response.headers.get("Content-Type", "")
            if response.status != expected:
                raise SmokeError(f"{method} {path.split('?')[0]} returned {response.status}; expected {expected}")
            for header in response.headers.get_all("Set-Cookie", []):
                cookies = SimpleCookie()
                cookies.load(header)
                if "seru_session" in cookies:
                    value = cookies["seru_session"].value
                    self.cookie = f"seru_session={value}" if value else None
            if not payload:
                return None, content_type
            if "application/json" in content_type:
                try:
                    return json.loads(payload), content_type
                except ValueError:
                    raise SmokeError(f"{path} returned invalid JSON") from None
            return payload, content_type


class Assets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        path = values.get("src") if tag == "script" else values.get("href") if tag == "link" else None
        if path and path.startswith("/assets/"):
            self.paths.append(path)


def require(condition, message):
    if not condition:
        raise SmokeError(message)


def wait_ready(client, timeout=90):
    deadline = time.monotonic() + timeout
    while True:
        try:
            health, _ = client.request("/api/health")
            if health.get("ready") and health.get("runtime_id") == "ayat" and health.get("pois", 0) > 0:
                require(health.get("snapshot_version"), "runtime has no canonical snapshot identity")
                return health
        except SmokeError:
            pass
        if time.monotonic() >= deadline:
            raise SmokeError("primary Ayat runtime did not become ready")
        time.sleep(1)


def check_ui(client):
    html, content_type = client.request("/")
    require("text/html" in content_type and b"<html" in html.lower(), "root is not the built UI")
    assets = Assets()
    assets.feed(html.decode("utf-8"))
    require(assets.paths, "built UI references no local assets")
    for path in dict.fromkeys(assets.paths):
        content, kind = client.request(path)
        require(content and "text/html" not in kind, "an asset returned HTML or empty content")
    deep, kind = client.request("/saved")
    require("text/html" in kind and deep == html, "saved deep link did not restore the UI shell")
    client.request("/api/delivery-smoke-missing", expected=404)
    return len(set(assets.paths))


def verify_saved(client, state):
    user, _ = client.request("/api/auth/me")
    require(user.get("id") == state["user_id"], "session restored the wrong account")
    rows, _ = client.request("/api/me/saved")
    require(any(row.get("poi_id") == state["poi_id"] and row.get("data") == state["saved"] for row in rows),
            "canonical saved recommendation did not survive")


def verify_logout(client):
    old_cookie = client.cookie
    require(old_cookie, "authentication did not set a session cookie")
    client.request("/api/auth/logout", method="POST", expected=204)
    revoked, _ = client.request("/api/auth/me", cookie=old_cookie)  # guests (incl. a revoked session) get 200 {"user": null}
    require(revoked == {"user": None}, "revoked session is still authenticated")
    client.cookie = None


def state_path(value):
    path = Path(value).expanduser().resolve()
    require(not path.is_relative_to(Path(__file__).resolve().parents[1]), "session state must be outside the repository")
    return path


def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", dir=path.parent, prefix=".delivery-", delete=False) as output:
            temporary = Path(output.name)
            json.dump(state, output)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def run(base_url, path, resume=False):
    path = state_path(path)
    require(resume or not path.exists(), "state already exists; use --resume or a new temporary path")
    if resume:
        try:
            state = json.loads(path.read_text())
        except (OSError, ValueError):
            raise SmokeError("could not read temporary smoke state") from None
        require(state.get("version") == 1 and state.get("base_url") == base_url.rstrip("/"), "state belongs to a different runtime origin")
        client = Client(base_url, state["cookie"])
    else:
        state = None
        client = Client(base_url)
    health = wait_ready(client)
    assets = check_ui(client)
    if resume:
        require(health["snapshot_version"] == state["snapshot_version"], "canonical snapshot changed across restart")
        verify_saved(client, state)
        verify_logout(client)
        path.unlink()
    else:
        email, password = f"delivery-{secrets.token_hex(12)}@example.com", secrets.token_urlsafe(32)
        user, _ = client.request("/api/auth/register", "POST", {"name": "Delivery Smoke", "email": email, "password": password, "lang": "en"}, expected=201)
        require(client.cookie, "registration did not set a session")
        primary_cookie = client.cookie
        result, _ = client.request("/api/recommend", "POST", {
            "query": "кофе рядом", "landmark": "baiterek", "lang": "en", "time_budget_min": 90,
            "want_route": False, "now": "2026-10-19T11:00:00+05:00"})
        recommendations = [r for r in result.get("recommendations", []) if r.get("source") == "poi_data" and ":" in r.get("poi_id", "")
                           and not r["poi_id"].startswith(("test:", "idea-"))]
        require(recommendations, "runtime returned no real canonical recommendation")
        card = recommendations[0]
        nearby, _ = client.request("/api/pois?" + urllib.parse.urlencode({"lat": card["lat"], "lon": card["lon"], "radius_m": 500, "limit": 1000}))
        require(any(p.get("id") == card["poi_id"] for p in nearby), "recommended ID is absent from the canonical POI API")
        saved = {k: v for k, v in {"name": card["name"], "category": card.get("category_label", card["category"]),
                 "categoryKey": card.get("category_detail", card["category"]), "lat": card["lat"], "lon": card["lon"],
                 "why": card["why"], "action": card["what_to_do"], "url": card.get("source_url"),
                 "visit": card.get("visit_suggested_min", card["visit_min"][0]), "visitRange": card["visit_min"],
                 "travel": card["travel_min"], "mode": card.get("travel_mode", "walk")}.items() if v is not None}
        endpoint = "/api/me/saved/" + urllib.parse.quote(card["poi_id"], safe="")
        client.request(endpoint, "PUT", {"data": saved})
        state = {"version": 1, "base_url": client.base, "cookie": primary_cookie, "user_id": user["id"],
                 "poi_id": card["poi_id"], "saved": saved, "snapshot_version": health["snapshot_version"]}
        verify_saved(client, state)
        # Verify logout now using another session, preserving the one used after restart.
        client.request("/api/auth/login", "POST", {"email": email, "password": password})
        verify_logout(client)
        client.cookie = primary_cookie
        verify_saved(client, state)
        save_state(path, state)
    return {"ok": True, "phase": "resumed" if resume else "initial", "runtime_id": health["runtime_id"],
            "assets_checked": assets, "canonical_saved": True, "logout_replay_rejected": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--state", required=True, help="private temporary state path outside the repository")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    try:
        result = run(args.base_url, args.state, args.resume)
    except (SmokeError, KeyError, TypeError) as error:
        message = str(error) if isinstance(error, SmokeError) else "runtime returned an unexpected response shape"
        print(f"delivery smoke failed: {message}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
