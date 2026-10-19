"""Safety layers (ported from the team backend by Abegerov4, adapted): PII masking, prompt-injection
sentence filter, untrusted-data wrapping, cleaning of LLM text before it is shown, rate limiting.

The system prompt is not a security boundary, so everything critical is done in code.
"""
from __future__ import annotations

import json
import re
import time
from collections import defaultdict, deque


class RateLimiter:
    """Tiny in-memory sliding-window limiter per client key (kept in RAM for the window only, never logged)."""

    def __init__(self, per_min: int, window_s: float = 60.0):
        self.per_min, self.window_s = per_min, window_s
        self._hits: dict[str, deque] = defaultdict(deque)

    def limited(self, key: str) -> bool:
        q, now = self._hits[key], time.time()
        while q and now - q[0] > self.window_s:
            q.popleft()
        if len(q) >= self.per_min:
            return True
        q.append(now)
        if len(self._hits) > 10000:  # bound memory: forget idle clients
            for k in [k for k, v in self._hits.items() if not v or now - v[-1] > self.window_s]:
                self._hits.pop(k, None)
        return False

PII_PATTERNS = {
    "EMAIL": r"[\w.+-]+@[\w-]+\.[\w.]+",
    "PHONE": r"(?:\+7|\b8)[\s\-()]*\d{3}[\s\-()]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}",
    "CARD": r"\b(?:\d[ -]?){15,18}\d\b",
    "IBAN": r"\bKZ\d{2}[A-Z0-9]{16}\b",
    "IIN": r"\b\d{12}\b",
}

INJECTION_PATTERNS = [
    r"ignore (all |the )?(previous|above|prior) (instructions|prompts?)",
    r"disregard (all |the )?(previous|above) ",
    r"(system|developer) prompt",
    r"you are now ",
    r"игнорируй\w* (все |предыдущие |прошлые )*(инструкции|указания|правила)",
    r"забудь (все |предыдущие )*(инструкции|правила)",
    r"(системн\w+|исходн\w+) (промпт|инструкци\w+)",
    r"ты теперь ",
    r"выведи (свой |весь )?(промпт|инструкци)",
    r"нұсқаулар\w* елеме",  # kk: "ignore the instructions"
]
_INJ = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]


def mask_pii(text: str) -> tuple[str, bool]:
    """Replace phones, emails, card/IBAN numbers and IINs with placeholders before any LLM call."""
    out = text or ""
    for label, pattern in PII_PATTERNS.items():
        out = re.sub(pattern, f"[{label}]", out)
    return out, out != (text or "")


def looks_like_injection(text: str) -> bool:
    return any(p.search(text or "") for p in _INJ)


def strip_injection(text: str) -> tuple[str, bool]:
    """Drop sentences that try to override instructions; keep the rest of the request."""
    parts = re.split(r"(?<=[.!?\n])\s+", text or "")
    kept = [s for s in parts if not looks_like_injection(s)]
    return " ".join(kept).strip(), len(kept) != len(parts)


def wrap_untrusted(payload) -> str:
    """POI texts come from user-editable open data: they are data, never instructions."""
    body = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    body = body.replace("</untrusted_data>", "")
    return f"<untrusted_data>\n{body}\n</untrusted_data>"


def strip_links(text: str) -> str:
    """No links or images from LLM text (exfiltration through rendering)."""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text or "")
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"(?i)\b(?:https?|ftp|javascript|data|vbscript|file):\S*", "", text)
    text = re.sub(r"(?i)\bwww\.\S+", "", text)
    text = re.sub(r"(?<![\w:])//[^\s)\]]+", "", text)
    while text.count(")") > text.count("("):
        i = text.rfind(")")
        text = text[:i] + text[i + 1:]
    return text


OPEN_CLAIM = re.compile(
    r"(сейчас\s+(?:открыт|работа)|открыт[оа]?\s+(?:сейчас|круглосуточно)|работает\s+(?:сейчас|круглосуточно|без\s+перерыв)|"
    r"круглосуточно|без\s+перерыв\w*|open\s+(?:now|24)|currently\s+open|24/7|қазір\s+(?:ашық|жұмыс)|тәулік\s+бойы)",
    re.IGNORECASE)


def drop_unverified_open_claims(text: str) -> str:
    """Remove sentences that claim a place is open (now / 24h) — hours are shown by code, not the LLM."""
    sentences = re.split(r"(?<=[.!?])\s+", text or "")
    return " ".join(s for s in sentences if not OPEN_CLAIM.search(s)).strip()
