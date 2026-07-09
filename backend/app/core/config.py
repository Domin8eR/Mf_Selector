from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Look for .env in backend/ first, then project root
        env_file=[".env", "../.env"],
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    environment: str = "development"
    debug: bool = False
    allowed_origins: list[str] = ["http://localhost:5173"]

    # Database (sync SQLAlchemy — NOT async)
    database_url: str = "postgresql://altstreet:altstreet_dev@localhost:5432/altstreet"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # S3 / MinIO (S3-compatible interface)
    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key_id: str = "altstreet"
    s3_secret_access_key: str = "change_me"
    s3_bucket_name: str = "altstreet-dev"

    # Security / JWT
    secret_key: str = "change_me_generate_32_char_hex_string_here"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 480

    # AI — LLM provider selection ("anthropic" or "openai")
    llm_provider: str = "anthropic"
    llm_model: str = ""  # empty = use provider default

    # AI — Anthropic
    anthropic_api_key: str = ""

    # AI — OpenAI
    openai_api_key: str = ""

    # AI observability — Langfuse (single provider)
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    # Error reporting
    sentry_dsn: str = ""

    # Versioning defaults (overridden by DB at runtime)
    data_version: str = "0"
    rule_version: str = "0"
    calculation_version: str = "0"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings: Settings = get_settings()
