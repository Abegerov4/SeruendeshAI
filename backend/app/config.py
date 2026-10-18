"""Настройки из переменных окружения (.env в корне репозитория или в backend/)."""
import os
from dataclasses import dataclass
from datetime import timedelta, timezone
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent

load_dotenv(REPO_ROOT / ".env")
load_dotenv(BACKEND_DIR / ".env")

# Казахстан с 2024 года живёт в едином поясе UTC+5
ASTANA_TZ = timezone(timedelta(hours=5), "Asia/Astana")

# Грубые границы Астаны — координаты вне них считаем ошибкой ввода
ASTANA_BBOX = (50.95, 71.15, 51.35, 71.75)  # south, west, north, east


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


DEFAULT_PRICES = {"gpt-6.1-sol": (2.0, 10.0), "gpt-5.4-mini": (0.75, 4.5)}


def _prices(raw: str) -> dict[str, tuple[float, float]]:
    """LLM_PRICES='gpt-6.1-sol=2.5/10,gpt-5.4-mini=0.25/2' — цены за 1M токенов (input/output)."""
    out = {}
    for item in filter(None, (p.strip() for p in raw.split(","))):
        try:
            model, pair = item.split("=")
            inp, outp = pair.split("/")
            out[model.strip()] = (float(inp), float(outp))
        except ValueError:
            continue
    return out


@dataclass(frozen=True)
class Settings:
    llm_api_key: str | None
    llm_base_url: str | None
    llm_fast_model: str        # разбор запроса: быстро, temperature=0
    llm_decision_model: str    # выбор мест и объяснение «почему»: свежая reasoning-модель
    llm_reasoning_effort: str
    llm_timeout_s: float
    llm_decision_timeout_s: float
    llm_prices: dict[str, tuple[float, float]]  # model -> ($ за 1M input, $ за 1M output)
    cache_ttl_s: int
    cache_max_items: int
    mock_rag: bool
    fixture_path: Path
    cors_origins: list[str]


@lru_cache
def get_settings() -> Settings:
    return Settings(
        llm_api_key=(os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
                     or os.getenv("openai_api_key") or "").strip() or None,
        llm_base_url=os.getenv("LLM_BASE_URL") or None,
        llm_fast_model=os.getenv("LLM_FAST_MODEL", "gpt-5.4-mini"),
        llm_decision_model=os.getenv("LLM_DECISION_MODEL", "gpt-6.1-sol"),
        llm_reasoning_effort=os.getenv("LLM_REASONING_EFFORT", "low"),
        llm_timeout_s=float(os.getenv("LLM_TIMEOUT_S", "25")),
        llm_decision_timeout_s=float(os.getenv("LLM_DECISION_TIMEOUT_S", "8")),
        # $ за 1M токенов input/output; значения по умолчанию сверены с расчётом стоимости в Langfuse
        llm_prices={**DEFAULT_PRICES, **_prices(os.getenv("LLM_PRICES", ""))},
        cache_ttl_s=int(os.getenv("CACHE_TTL_S", "900")),
        cache_max_items=int(os.getenv("CACHE_MAX_ITEMS", "500")),
        mock_rag=_bool("MOCK_RAG", False),
        fixture_path=Path(os.getenv("POI_FIXTURE", BACKEND_DIR / "tests" / "fixtures" / "pois_sample.json")),
        cors_origins=[o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()],
    )
