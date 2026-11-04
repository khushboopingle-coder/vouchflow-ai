"""
FastAPI dependency: who is calling, and which workspace may they use?

Every data route uses `current_account`. It reads "Authorization: Bearer <token>"
(from POST /auth/login), checks the signature and expiry, and checks that the user still
owns the workspace in the token. Anything wrong -> 401. Routes then pass
account.workspace_id to the services, which only ever read that workspace.
"""

from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from backend.auth.tokens import verify_token
from backend.database.db import get_db
from backend.services import api_key_service
from backend.services.auth_service import Account, account_for

UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not logged in, or the login has expired. Get a token from POST /auth/login.",
    headers={"WWW-Authenticate": "Bearer"},
)


def current_account(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> Account:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise UNAUTHORIZED
    data = verify_token(authorization.split(" ", 1)[1].strip())
    if data is None:
        raise UNAUTHORIZED
    account = account_for(db, data.user_id, data.workspace_id)
    if account is None:
        raise UNAUTHORIZED
    return account


@dataclass(frozen=True)
class APIKeyAccount:
    """Who an API key stands for: exactly one workspace."""
    key_id: int
    workspace_id: int
    key_name: str
    key_prefix: str


UNAUTHORIZED_KEY = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Missing or invalid API key. Send your key in the X-API-Key header "
           "(create one on the dashboard's Settings page).",
)


def api_key_account(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> APIKeyAccount:
    """Automation routes (/api/...): the X-API-Key header identifies the workspace.
    Missing, wrong or revoked key -> 401. A login token does NOT work here, and an API key
    does not work on the dashboard routes."""
    record = api_key_service.authenticate_api_key(db, x_api_key)
    if record is None:
        raise UNAUTHORIZED_KEY
    return APIKeyAccount(record.id, record.workspace_id, record.name, record.key_prefix)
