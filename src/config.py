from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ANTHROPIC_API_KEY: str
    AUTHORIZED_USERS: str = ""
    GMAIL_WEBHOOK_SECRET: str = ""
    DEFAULT_MODEL: str = "claude-sonnet-4-5-20250929"
    MAX_XLSX_SIZE_MB: int = 10
    MAX_PREVIEW_ROWS: int = 50
    LOG_LEVEL: str = "INFO"
    GOOGLE_CHAT_PROJECT_NUMBER: str = ""
    MENTION_TRIGGER: bool = True
    GOOGLE_CHAT_SERVICE_ACCOUNT_FILE: str = ""
    THREAD_CONTEXT_TTL_SECONDS: int = 3600
    THREAD_CONTEXT_MAX_ENTRIES: int = 500
    THREAD_CONTEXT_MAX_TURNS: int = 10
    GCS_BUCKET_NAME: str = ""
    GCS_SIGNED_URL_EXPIRATION_HOURS: int = 24
    GCS_GENERATED_FILES_PREFIX: str = "generated/"
    GCS_SERVICE_ACCOUNT_FILE: str = ""
    FILE_RETENTION_HOURS: int = 24
    COMPLEX_MODEL: str = ""
    CLAUDE_TIMEOUT_SECONDS: int = 60
    CONTEXT_WINDOW_TOKENS: int = 200_000
    USAGE_WARNING_THRESHOLD: float = 0.20
    USAGE_CRITICAL_THRESHOLD: float = 0.05
    RATE_LIMIT_RPM: int = 50
    RATE_LIMIT_INPUT_TPM: int = 80_000
    RATE_LIMIT_WARNING_THRESHOLD: float = 0.80
    DAILY_BUDGET_USD: float = 5.00
    COST_WARNING_THRESHOLD: float = 0.80
    SONNET_INPUT_COST_PER_M: float = 3.00
    SONNET_OUTPUT_COST_PER_M: float = 15.00
    OPUS_INPUT_COST_PER_M: float = 5.00
    OPUS_OUTPUT_COST_PER_M: float = 25.00

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @property
    def authorized_users_list(self) -> list[str]:
        if not self.AUTHORIZED_USERS.strip():
            return []
        return [u.strip() for u in self.AUTHORIZED_USERS.split(",")]


@lru_cache
def get_settings() -> Settings:
    return Settings()
