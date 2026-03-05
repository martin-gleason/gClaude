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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @property
    def authorized_users_list(self) -> list[str]:
        if not self.AUTHORIZED_USERS.strip():
            return []
        return [u.strip() for u in self.AUTHORIZED_USERS.split(",")]


@lru_cache
def get_settings() -> Settings:
    return Settings()
