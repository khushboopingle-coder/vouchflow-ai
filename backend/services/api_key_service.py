"""
API keys for automation (Phase 4)
=================================
A workspace owner creates keys on the dashboard's Settings page and gives one to n8n.
- The key looks like  vf_<43 random characters>  and is shown ONCE, when it is created.
- Only its SHA-256 hash is stored (keys are long random strings, so a fast hash is safe;
  passwords are different and use bcrypt). A database leak therefore reveals no usable key.
- A key belongs to exactly one workspace: whoever holds it can only reach that workspace.
- A key can be revoked at any time; a revoked key is refused immediately.
"""

import hashlib
import secrets
from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.database.models import APIKey, AuditLog

KEY_PREFIX = "vf_"
MAX_ACTIVE_KEYS_PER_WORKSPACE = 10
MAX_NAME_LENGTH = 100


class APIKeyError(ValueError):
    """A problem the user can fix (shown as-is on the Settings page)."""


def hash_key(raw_key: str) -> str:
    return hashlib.sha256((raw_key or "").encode("utf-8")).hexdigest()


def generate_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def create_api_key(db: Session, workspace_id: int, user_id: Optional[int], name: str,
                   who: str = "system") -> Tuple[APIKey, str]:
    """Creates a key and returns (record, the plain key). The plain key is NOT stored:
    this is the only moment it can be shown."""
    name = " ".join((name or "").split())
    if not name:
        raise APIKeyError("Please give the key a name, for example 'n8n Gmail'.")
    if len(name) > MAX_NAME_LENGTH:
        raise APIKeyError(f"The name is too long (maximum {MAX_NAME_LENGTH} characters).")
    active = db.query(APIKey).filter(APIKey.workspace_id == workspace_id, APIKey.revoked_at.is_(None)).count()
    if active >= MAX_ACTIVE_KEYS_PER_WORKSPACE:
        raise APIKeyError(f"You already have {active} active keys. Revoke one you no longer use first.")

    raw = generate_key()
    record = APIKey(workspace_id=workspace_id, created_by_user_id=user_id, name=name,
                    key_prefix=raw[:10], key_hash=hash_key(raw), created_at=datetime.utcnow())
    db.add(record)
    db.add(AuditLog(who=who, action="api_key_created", workspace_id=workspace_id,
                    details=f"API key '{name}' ({record.key_prefix}...) created."))
    db.commit()
    db.refresh(record)
    return record, raw


def list_api_keys(db: Session, workspace_id: int) -> List[APIKey]:
    return (db.query(APIKey).filter(APIKey.workspace_id == workspace_id)
            .order_by(APIKey.created_at.desc(), APIKey.id.desc()).all())


def revoke_api_key(db: Session, workspace_id: int, key_id: int, who: str = "system") -> bool:
    """Revokes one of THIS workspace's keys. False if there is no such active key here."""
    record = (db.query(APIKey)
              .filter(APIKey.id == key_id, APIKey.workspace_id == workspace_id, APIKey.revoked_at.is_(None))
              .first())
    if record is None:
        return False
    record.revoked_at = datetime.utcnow()
    db.add(AuditLog(who=who, action="api_key_revoked", workspace_id=workspace_id,
                    details=f"API key '{record.name}' ({record.key_prefix}...) revoked."))
    db.commit()
    return True


def authenticate_api_key(db: Session, raw_key: Optional[str]) -> Optional[APIKey]:
    """The key record if the key is known and not revoked, otherwise None."""
    if not raw_key or not raw_key.startswith(KEY_PREFIX) or len(raw_key) > 200:
        return None
    record = db.query(APIKey).filter(APIKey.key_hash == hash_key(raw_key)).first()
    if record is None or record.revoked_at is not None:
        return None
    record.last_used_at = datetime.utcnow()
    db.commit()
    return record
