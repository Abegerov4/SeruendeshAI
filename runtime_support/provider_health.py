"""Readiness evidence from completed calls; health requests never invoke a provider."""
from datetime import datetime, timezone
from threading import Lock
import time


class ProbeState:
    def __init__(self, *, clock=time.monotonic):
        self._clock = clock
        self._lock = Lock()
        self._records = {}

    def record(self, configuration: str, scope: str, ok: bool, model: str, *, error: str | None = None):
        with self._lock:
            # A new account/configuration cannot inherit previous readiness.
            self._records = {key: value for key, value in self._records.items() if key[0] == configuration}
            self._records[(configuration, scope)] = {
                "ok": ok, "at": self._clock(), "verified_at": datetime.now(timezone.utc).isoformat() if ok else None,
                "model": model, "error": error,
            }

    def describe(self, configuration: str, scopes: set[str], *, configured: bool, ttl_s: float = 300) -> dict:
        if not configured:
            return {"status": "off", "verified_at": None}
        with self._lock:
            recent = [self._records.get((configuration, scope)) for scope in scopes]
            fresh = [row for row in recent if row is not None and self._clock() - row["at"] <= ttl_s]
            if any(not row["ok"] for row in fresh):
                status = "degraded"
            elif scopes and len(fresh) == len(scopes):
                status = "ok"
            else:
                status = "configured"
            verified = min((row["verified_at"] for row in fresh), default=None) if status == "ok" else None
            return {"status": status, "verified_at": verified}
