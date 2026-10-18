from __future__ import annotations

from functools import lru_cache

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

    embed_model: str = "e5-large"  # e5-large | e5-base | e5-small | off
    weather_enabled: bool = True

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173"
    cors_origin_regex: str = r"https://.*\.(vercel\.app|netlify\.app|pages\.dev)"
    response_cache_ttl_s: int = 600
    rate_limit_per_min: int = 30
    log_level: str = "INFO"

    @property
    def llm_chain(self) -> list[str]:
        return [m.strip() for m in self.llm_models.split(",") if m.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
