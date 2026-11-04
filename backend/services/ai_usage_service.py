"""
Fair AI limits (Phase 3)
========================
The default explanation is the deterministic template (llm_used=False, free, instant).
A user may ask for a real Gemini explanation up to DAILY_AI_LIMIT times per day; each one
that Gemini actually wrote is counted in the ai_usage table. When the limit is reached,
no key is configured, or Gemini fails, the template is used silently.
"""

from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from backend.config import settings
from backend.database.models import AIUsage

DAILY_AI_LIMIT = 5


def _today() -> date:
    return date.today()


def used_today(db: Session, user_id: int) -> int:
    row = db.query(AIUsage).filter(AIUsage.user_id == user_id, AIUsage.day == _today()).first()
    return row.count if row else 0


def remaining_today(db: Session, user_id: Optional[int]) -> int:
    if user_id is None:
        return 0
    return max(0, DAILY_AI_LIMIT - used_today(db, user_id))


def ai_available() -> bool:
    """A Gemini key is configured (the limit is checked separately per user)."""
    return bool(settings.GEMINI_API_KEY)


def may_use_ai(db: Session, user_id: Optional[int]) -> bool:
    return ai_available() and remaining_today(db, user_id) > 0


def record_ai_use(db: Session, user_id: int) -> int:
    """Counts one real AI explanation for today; returns the new count."""
    row = db.query(AIUsage).filter(AIUsage.user_id == user_id, AIUsage.day == _today()).first()
    if row is None:
        row = AIUsage(user_id=user_id, day=_today(), count=0)
        db.add(row)
    row.count += 1
    db.commit()
    return row.count
