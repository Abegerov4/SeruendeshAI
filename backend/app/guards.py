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
    """Чистим текст LLM перед показом: никаких ссылок и картинок (утечка данных через рендер).

    Markdown-ссылка [текст](цель) → остаётся только текст; удаляются http(s)://, //host, javascript:, data:, vbscript:.
    """
    if not isinstance(text, str):
        return ""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)            # картинки целиком
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)        # ссылки → только подпись
    text = re.sub(r"(?i)\b(?:https?|ftp|javascript|data|vbscript|file):\S*", "", text)
    text = re.sub(r"(?<![\w:])//[^\s)\]]+", "", text)            # scheme-relative //host/path
    while text.count(")") > text.count("("):                    # хвосты от вырезанных ссылок
        i = text.rfind(")")
        text = text[:i] + text[i + 1:]
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([.,;:!?])", r"\1", text).strip()
    if not re.search(r"\w", text):                               # от текста остались только знаки
        return ""
    return text[:max_len].rstrip()


# Утверждения о доступности, которые нельзя делать без подтверждённых часов работы
OPEN_CLAIM = re.compile(
    r"(сейчас\s+(?:открыт|работа)|открыт[оа]?\s+(?:сейчас|круглосуточно)|работает\s+(?:сейчас|круглосуточно)|"
    r"часы\s+(?:работы\s+)?подтвержден|круглосуточно|open\s+(?:now|24)|currently\s+open|ашық|қазір\s+жұмыс)",
    re.IGNORECASE,
)


def drop_unverified_open_claims(text: str) -> str:
    """Убираем предложения, где модель утверждает «открыто сейчас», если статус часов не 'open'."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    kept = [s for s in sentences if not OPEN_CLAIM.search(s)]
    return " ".join(kept).strip()
