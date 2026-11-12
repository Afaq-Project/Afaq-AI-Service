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
    ai_model: str = "gemini-3.6-flash"
    ai_timeout_seconds: float = 60.0
    ai_max_retries: int = 2
    ai_chat_max_tokens: int = 4096
    ai_review_max_tokens: int = 8192
    ai_history_limit: int = 20
    ai_refusal_fallbacks: bool = True

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

    # Filebase S3 configuration
    filebase_endpoint: str = "https://s3.filebase.com"
    filebase_region: str = "us-east-1"
    filebase_bucket: str = ""
    filebase_access_key: str = ""
    filebase_secret_key: str = ""

    @property
    def s3_endpoint(self) -> str:
        """Returns the configured S3 endpoint URL (Filebase or AWS)."""
        return (
            self.filebase_endpoint
            or self.aws_s3_endpoint_url
            or "https://s3.filebase.com"
        )

    @property
    def s3_bucket(self) -> str:
        """Returns the effective S3 bucket name."""
        return self.filebase_bucket or self.s3_attachments_bucket

    @property
    def s3_access_key(self) -> str:
        """Returns the effective S3 access key ID."""
        return self.filebase_access_key or self.aws_access_key_id

    @property
    def s3_secret_key(self) -> str:
        """Returns the effective S3 secret access key."""
        return self.filebase_secret_key or self.aws_secret_access_key

    @property
    def s3_region(self) -> str:
        """Returns the effective S3 region."""
        return self.filebase_region or self.aws_region or "us-east-1"


@lru_cache
def get_settings() -> Settings:
    """يرجع نسخة واحدة من الإعدادات (مخزّنة مؤقتاً)."""
    return Settings()
