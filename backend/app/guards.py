"""Защитные слои: PII-маскирование, детектор prompt injection, маркировка недоверенных данных.

См. ai_security.md §4.3–4.5, §6.2. Системный промпт — не барьер, поэтому всё критичное делаем кодом.
"""
import json
import re

PII_PATTERNS = {
    "EMAIL": r"[\w.+-]+@[\w-]+\.[\w.]+",
    "PHONE": r"(?:\+7|8)[\s\-()]*\d{3}[\s\-()]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}",
    "CARD": r"\b(?:\d[ -]?){15,18}\d\b|\bKZ\d{2}[A-Z0-9]{16}\b",
    "IIN": r"\b\d{12}\b",
}

INJECTION_PATTERNS = [
    r"ignore (all |the )?(previous|above|prior) (instructions|prompts?)",
    r"disregard (all |the )?(previous|above) ",
    r"(system|developer) prompt",
    r"you are now ",
    r"\bDAN\b",
    r"игнорируй (все |предыдущие |прошлые )*(инструкции|указания|правила)",
    r"забудь (все |предыдущие )*(инструкции|правила)",
    r"(системн\w+|исходн\w+) (промпт|инструкци\w+)",
    r"ты теперь ",
    r"нұсқаулар\w* елеме",  # kk: «игнорируй инструкции»
]


def mask_pii(text: str) -> str:
    for label, pattern in PII_PATTERNS.items():
        text = re.sub(pattern, f"[{label}]", text)
    return text


def looks_like_injection(text: str) -> bool:
    low = text.lower()
    return any(re.search(p, low, flags=re.IGNORECASE) for p in INJECTION_PATTERNS)


def wrap_untrusted(payload) -> str:
    """Данные POI пришли из интернета — это данные, а не инструкции."""
    body = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    body = body.replace("</untrusted_data>", "")
    return f"<untrusted_data>\n{body}\n</untrusted_data>"


def clean_llm_text(text: str, max_len: int = 300) -> str:
    """Срезаем ссылки/markdown-картинки из текста LLM (утечка через рендер) и ограничиваем длину."""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len].rstrip()
