from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    APP_NAME: str = "NetSentinel"
    LOG_LEVEL: str = "INFO"

    # Scanning defaults — conservative values for safe operation.
    SCAN_TIMEOUT: float = 3.0
    SCAN_MAX_CONCURRENCY: int = 50
    MONITOR_INTERVAL: int = 30

    # Database (v0.3) — empty string means "not configured".
    # The application continues to function without a database for scan/monitor.
    DATABASE_URL: str = ""


settings = Settings()
