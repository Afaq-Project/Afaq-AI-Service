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


@lru_cache
def get_settings() -> Settings:
    """يرجع نسخة واحدة من الإعدادات (مخزّنة مؤقتاً)."""
    return Settings()
