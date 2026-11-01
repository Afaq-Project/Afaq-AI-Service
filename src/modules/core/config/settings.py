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
    environment: str = "development"
    log_level: str = "INFO"

    api_key_header_name: str = "X-API-Key"

    main_service_webhook_url: str = ""
    main_service_webhook_secret: str = ""
    webhook_timeout: float = 15.0

    # AI & LLM settings (for Stage 0 Discovery & Stage 1 Schema Synthesis)
    google_api_key: str = ""
    anthropic_api_key: str = ""
    ai_model: str = "gemini-2.0-flash"
    ai_timeout_seconds: float = 60.0
    ai_max_retries: int = 2

    # Crawling & Browser settings (Ultra-low memory container constraints)
    crawler_max_concurrent_crawls: int = 1
    crawler_page_timeout_sec: int = 30
    crawler_max_operation_timeout_sec: int = 1200
    crawler_default_rate_limit_delay_sec: float = 1.0

    # S3 Storage settings for document & application attachments
    s3_attachments_bucket: str = "afaq-attachments"
    aws_region: str = "us-east-1"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_s3_endpoint_url: str = ""


@lru_cache
def get_settings() -> Settings:
    """يرجع نسخة واحدة من الإعدادات (مخزّنة مؤقتاً)."""
    return Settings()
