"""
Startup check (Phase 6): tells you clearly WHICH environment variable is missing or unsafe.

Used by the API when it starts (backend/main.py) and by the dashboard (dashboard/app.py).
- In ENVIRONMENT=production a missing/unsafe REQUIRED setting stops the start with a message
  that names the variable and says what to do (instead of a confusing crash later, or - worse -
  silently losing data on a temporary SQLite file).
- Other problems are printed as warnings (the app still runs, with that feature off).
The values themselves are never printed - only the variable names.
"""

import sys
from dataclasses import dataclass
from typing import List, Optional

from backend.config import settings

MIN_SECRET_LENGTH = 32


@dataclass(frozen=True)
class Problem:
    level: str      # "error" (stops a production start) or "warning"
    variable: str
    message: str

    def __str__(self) -> str:
        return f"[{self.level.upper()}] {self.variable}: {self.message}"


def is_production() -> bool:
    return settings.ENVIRONMENT.strip().lower() == "production"


def check_environment(cfg=None) -> List[Problem]:
    """All configuration problems, errors first. `cfg` is the settings object (tests pass their own)."""
    cfg = cfg or settings
    production = cfg.ENVIRONMENT.strip().lower() == "production"
    problems: List[Problem] = []

    if production and cfg.is_sqlite:
        problems.append(Problem(
            "error", "DATABASE_URL",
            "is not set (or points to a SQLite file). In production your data would live in a temporary file and "
            "disappear on every restart. Set DATABASE_URL to your Neon PostgreSQL link "
            "(postgresql://user:password@host/dbname?sslmode=require)."))

    if not cfg.VOUCHFLOW_SECRET_KEY:
        problems.append(Problem(
            "error" if production else "warning", "VOUCHFLOW_SECRET_KEY",
            "is not set. API login tokens would be signed with a random key that changes on every restart, so every "
            "user would be logged out. Set it to a long random value (at least 32 characters), for example the output "
            "of: python -c \"import secrets; print(secrets.token_urlsafe(48))\""))
    elif len(cfg.VOUCHFLOW_SECRET_KEY) < MIN_SECRET_LENGTH:
        problems.append(Problem(
            "error" if production else "warning", "VOUCHFLOW_SECRET_KEY",
            f"is too short ({len(cfg.VOUCHFLOW_SECRET_KEY)} characters). Use at least {MIN_SECRET_LENGTH}."))

    if not cfg.GEMINI_API_KEY:
        problems.append(Problem(
            "warning", "GEMINI_API_KEY",
            "is not set. Invoices cannot be read by AI (uploads and automation land in 'needs review') and explanations "
            "use the plain template. Everything else works."))

    if production and "localhost" in cfg.DASHBOARD_URL:
        problems.append(Problem(
            "warning", "DASHBOARD_URL",
            "still points to localhost, so the links in n8n alerts will not open. Set it to your public dashboard "
            "address, e.g. https://your-app.streamlit.app"))

    return sorted(problems, key=lambda p: p.level != "error")


def format_problems(problems: List[Problem]) -> str:
    return "\n".join(str(p) for p in problems)


def run_startup_check(stream=None, exit_on_error: bool = True) -> List[Problem]:
    """Print every problem. In production an error stops the start (RuntimeError) after listing them all."""
    stream = stream or sys.stderr
    problems = check_environment()
    if problems:
        print("VouchFlow startup check:\n" + format_problems(problems), file=stream)
    errors = [p for p in problems if p.level == "error"]
    if errors and is_production() and exit_on_error:
        raise RuntimeError(
            "VouchFlow cannot start: fix these environment variables first -> "
            + ", ".join(p.variable for p in errors) + ". See the messages above and DEPLOY.md.")
    return problems
