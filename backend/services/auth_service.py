"""
Account Service for VouchFlow AI (Phase 2)
==========================================
- signup(): new user + their own private workspace (+ optional copy of the sample data)
- login(): checks email + password; the same answer for "no such email" and "wrong
  password", so nobody can find out which emails have accounts
Passwords are hashed with bcrypt (backend/auth/passwords.py); the plain text is never stored.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from backend.auth.passwords import MIN_PASSWORD_LENGTH, hash_password, verify_password
from backend.database.models import AuditLog, User, Workspace
from backend.services import workspace_service

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Compared against when the email is unknown, so a failed login always takes as long
_DUMMY_HASH = hash_password("not-a-real-password-just-for-timing")


class AuthError(ValueError):
    """A problem the user can fix (shown as-is in the UI / API)."""


@dataclass
class Account:
    user_id: int
    email: str
    workspace_id: int
    workspace_name: str


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _account(user: User, ws: Workspace) -> Account:
    return Account(user_id=user.id, email=user.email, workspace_id=ws.id, workspace_name=ws.name)


def signup(db: Session, email: str, password: str, load_sample: bool = True) -> Account:
    email = normalize_email(email)
    if not EMAIL_RE.match(email) or len(email) > 255:
        raise AuthError("Please enter a valid email address.")
    if len(password or "") < MIN_PASSWORD_LENGTH:
        raise AuthError(f"The password must be at least {MIN_PASSWORD_LENGTH} characters.")
    try:
        password_hash = hash_password(password)
    except ValueError as exc:
        raise AuthError(str(exc)) from exc
    if db.query(User).filter(User.email == email).first():
        raise AuthError("An account with this email already exists. Please log in.")

    user = User(email=email, password_hash=password_hash, created_at=datetime.utcnow())
    db.add(user)
    db.flush()
    ws = Workspace(name=f"{email.split('@')[0]}'s workspace", owner_user_id=user.id,
                   is_sample=False, created_at=datetime.utcnow())
    db.add(ws)
    db.flush()
    db.add(AuditLog(who=email, action="user_signup", workspace_id=ws.id,
                    details="Account and private workspace created."))
    db.commit()

    if load_sample:
        workspace_service.load_sample_data(db, ws.id, who=email)
    return _account(user, ws)


def login(db: Session, email: str, password: str) -> Optional[Account]:
    """The account if email + password are right, otherwise None."""
    user = db.query(User).filter(User.email == normalize_email(email)).first()
    if user is None:
        verify_password(password or "", _DUMMY_HASH)
        return None
    if not verify_password(password or "", user.password_hash):
        return None
    ws = workspace_service.get_user_workspace(db, user.id)
    if ws is None:
        return None
    return _account(user, ws)


def account_for(db: Session, user_id: int, workspace_id: int) -> Optional[Account]:
    """The account behind a login token, if the user still owns that workspace."""
    user = db.query(User).filter(User.id == user_id).first()
    ws = workspace_service.get_workspace(db, workspace_id)
    if user is None or ws is None or ws.owner_user_id != user.id:
        return None
    return _account(user, ws)
