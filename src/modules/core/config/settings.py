from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """إعدادات التطبيق المقروءة من متغيرات البيئة."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = ""
    profile_api_database_url: str = ""
    environment: str = "development"
    log_level: str = "INFO"

    api_key_header_name: str = "X-API-Key"

    main_service_webhook_url: str = ""
    main_service_webhook_secret: str = ""
    webhook_timeout: float = 15.0

    anthropic_api_key: str = ""
    ai_model: str = "claude-opus-5"
    ai_timeout_seconds: float = 120.0
    ai_max_retries: int = 1
    ai_chat_max_tokens: int = 4096
    ai_review_max_tokens: int = 8192
    ai_history_limit: int = 20
    ai_refusal_fallbacks: bool = True


@lru_cache
def get_settings() -> Settings:
    """يرجع نسخة واحدة من الإعدادات (مخزّنة مؤقتاً)."""
    return Settings()
