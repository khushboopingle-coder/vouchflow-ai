"""
Application Configuration
Loads settings from environment variables or a .env file.
Works seamlessly with SQLite or PostgreSQL without changing code.
"""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Database connection URL
    # SQLite by default, e.g. "sqlite:///./vouchflow.db"
    # To use PostgreSQL, set DATABASE_URL="postgresql://user:pass@host:5432/dbname" in .env
    DATABASE_URL: str = "sqlite:///./vouchflow.db"

    # Base folder where generated and uploaded files reside
    DATA_DIR: str = "./data"

    # Environment name: development, testing, or production
    ENVIRONMENT: str = "development"

    # Google Gemini AI settings (Phase 1 Invoice Reader)
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.5-flash-lite"
    GEMINI_MODEL_LIST: str = ""

    # 3-Way Matching Tolerance Settings
    # Differences up to this amount (in Rupees) are accepted as valid commercial rounding
    ROUNDING_TOLERANCE_RS: float = 1.00

    @property
    def gemini_models(self) -> list[str]:
        """Returns the list of configured Gemini models in priority fallback order."""
        if self.GEMINI_MODEL_LIST:
            models = [m.strip() for m in self.GEMINI_MODEL_LIST.split(",") if m.strip()]
            if models:
                return models
        return [self.GEMINI_MODEL] if self.GEMINI_MODEL else ["gemini-3.5-flash-lite"]

    # Pydantic v2 configuration to read from .env file
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def data_path(self) -> Path:
        """Returns the resolved Path object for DATA_DIR."""
        return Path(self.DATA_DIR).resolve()


# Singleton instance of settings
settings = Settings()
