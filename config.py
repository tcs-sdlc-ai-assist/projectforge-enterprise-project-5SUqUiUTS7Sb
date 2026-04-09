import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    SECRET_KEY: str = "change-me-in-production-use-a-long-random-string"
    DATABASE_URL: str = "sqlite+aiosqlite:///./projectforge.db"
    DEFAULT_ADMIN_USERNAME: str = "admin"
    DEFAULT_ADMIN_PASSWORD: str = "admin123"
    TOKEN_EXPIRY_SECONDS: int = 3600


settings = Settings()