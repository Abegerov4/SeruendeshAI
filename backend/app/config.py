from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.paths import BACKEND_DIR, ROOT_DIR


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(ROOT_DIR / ".env", BACKEND_DIR / ".env"), extra="ignore")

    openai_api_key: str = ""
    # generation fallback chain (first that answers wins); measured: gpt-6-luna effort=none ~2.5 s
    llm_models: str = "gpt-6-luna,gpt-5.6-luna,gpt-4.1-mini"
    llm_parse_model: str = "gpt-6-luna"
    llm_service_tier: str = "fast"  # "" = default tier; applies to the first model only
    llm_timeout_s: float = 8.0
    parse_timeout_s: float = 3.0
    llm_enabled: bool = True
    llm_warmup_enabled: bool = False  # opt in: startup probes incur provider charges
    photo_timeout_s: float = 12.0  # vision call of POST /api/recommend/photo
    # USD per 1M tokens [input, output] for cost logging (developers.openai.com/api/docs/pricing, Oct 2026).
    # Edit here or override with LLM_PRICES='{"model": [in, out]}'; "model@tier" = price on that service tier.
    # A model missing from the table -> cost_usd null.
    llm_prices: dict[str, tuple[float, float]] = {
        "gpt-6-luna": (0.10, 0.50), "gpt-6-luna@fast": (0.20, 1.00),
        "gpt-5.6-luna": (0.20, 1.20), "gpt-4.1-mini": (0.40, 1.60), "gpt-4o-mini": (0.15, 0.60),
    }

    embed_model: str = "e5-large"  # e5-large | e5-base | e5-small | off
    weather_enabled: bool = True

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173"
    cors_origin_regex: str = r"https://.*\.(vercel\.app|netlify\.app|pages\.dev)"
    response_cache_ttl_s: int = 600
    flight_domestic_buffer_min: int = 120
    flight_international_buffer_min: int = 180
    # "у меня 2 часа перед вылетом" from a tourist almost always means free time before heading to the airport:
    # without an explicit flight type no check-in reserve is subtracted, and the answer says so (note_flight_free_time)
    flight_unknown_buffer_min: int = 0
    deadline_road_uncertainty_min: int = 15
    route_max_snap_m: int = 500
    hours_max_age_days: int = 180
    readiness_profile: Literal["template", "llm"] = "template"
    provider_probe_ttl_s: int = 300
    # accounts
    database_url: str = ""          # Railway Postgres DATABASE_URL; empty -> local SQLite (backend/.local/app.db)
    secret_key: str = ""            # legacy setting; sessions now use random DB-backed tokens
    public_url: str = ""            # e.g. https://seruendesh.site (links in emails)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    rate_limit_per_min: int = 30
    mcp_rate_limit_per_min: int = 30  # MCP tool calls per client per minute
    photo_rate_limit_per_min: int = 10  # vision calls cost more
    log_level: str = "INFO"

    @property
    def llm_chain(self) -> list[str]:
        return [m.strip() for m in self.llm_models.split(",") if m.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
