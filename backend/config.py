"""
Application Configuration
Loads settings from environment variables or a .env file.

Database:
- DATABASE_URL in .env (or the environment) picks the database.
  e.g. a Neon PostgreSQL link "postgresql://user:pass@host/db?sslmode=require"
- If DATABASE_URL is not set, local SQLite is used: "sqlite:///./vouchflow.db"
- Always use `settings.database_url` (not DATABASE_URL) to connect: it adds the
  psycopg (v3) driver name that SQLAlchemy needs for PostgreSQL.
- The link is a secret: never print or log it.
"""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SQLITE_URL = "sqlite:///./vouchflow.db"


def normalize_database_url(url: str) -> str:
    """Makes a database link ready for SQLAlchemy.

    - empty            -> local SQLite (DEFAULT_SQLITE_URL)
    - postgres://...   -> postgresql+psycopg://...   (old Heroku-style alias)
    - postgresql://... -> postgresql+psycopg://...   (use the psycopg v3 driver)
    - anything else (sqlite, postgresql+psycopg, ...) is returned unchanged.
    Query options such as ?sslmode=require&channel_binding=require are kept.
    """
    url = (url or "").strip().strip('"').strip("'")
    if not url:
        return DEFAULT_SQLITE_URL
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


class Settings(BaseSettings):
    # Database connection link (see module docstring). Empty or missing -> local SQLite.
    DATABASE_URL: str = DEFAULT_SQLITE_URL

    # Base folder where generated and uploaded files reside
    DATA_DIR: str = "./data"

    # Environment name: development, testing, or production
    ENVIRONMENT: str = "development"

    # Google Gemini AI settings (Phase 1 Invoice Reader)
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.5-flash-lite"
    GEMINI_MODEL_LIST: str = ""

    # Signs login tokens for the API (Phase 2). Set a long random value in production.
    # Empty -> a random key per process is used (tokens stop working after a restart).
    VOUCHFLOW_SECRET_KEY: str = ""

    # 3-Way Matching Tolerance Settings
    # Differences up to this amount (in Rupees) are accepted as valid commercial rounding
    ROUNDING_TOLERANCE_RS: float = 1.00

    @property
    def database_url(self) -> str:
        """The link SQLAlchemy should use (driver name added, SQLite fallback)."""
        return normalize_database_url(self.DATABASE_URL)

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def database_kind(self) -> str:
        """'sqlite' or 'postgresql' — safe to print (no host, user or password)."""
        return self.database_url.split(":", 1)[0].split("+", 1)[0]

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
