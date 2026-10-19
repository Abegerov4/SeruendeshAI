"""In-memory TTL-кэш ответов /api/recommend.

Ключ — sha256 от (замаскированный запрос, округлённая локация, параметры, час).
Сырые координаты и текст запроса в кэше не лежат — только хэш ключа и готовый ответ.
"""
import hashlib
import json
import threading
import time
from collections import OrderedDict
from datetime import datetime

from .config import get_settings


class TTLCache:
    def __init__(self, ttl_s: int, max_items: int):
        self.ttl_s, self.max_items = ttl_s, max_items
        self._data: OrderedDict[str, tuple[float, dict]] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = self.misses = 0

    def get(self, key: str) -> dict | None:
        with self._lock:
            item = self._data.get(key)
            if item is None or item[0] < time.monotonic():
                self._data.pop(key, None)
                self.misses += 1
                return None
            self._data.move_to_end(key)
            self.hits += 1
            return item[1]

    def set(self, key: str, value: dict) -> None:
        if self.ttl_s <= 0:
            return
        with self._lock:
            self._data[key] = (time.monotonic() + self.ttl_s, value)
            self._data.move_to_end(key)
            while len(self._data) > self.max_items:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self.hits = self.misses = 0

    def stats(self) -> dict:
        return {"items": len(self._data), "hits": self.hits, "misses": self.misses, "ttl_s": self.ttl_s}


_s = get_settings()
responses = TTLCache(_s.cache_ttl_s, _s.cache_max_items)


def make_key(masked_query: str, location: tuple[float, float] | None, now: datetime, params: dict) -> str:
    raw = json.dumps({
        "q": " ".join(masked_query.lower().split()),
        "loc": [round(location[0], 3), round(location[1], 3)] if location else None,
        "now": now.isoformat(),  # exact temporal context; never reuse opening/deadline buckets
        **params,
    }, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()
