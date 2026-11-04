"""
Signed login tokens for the FastAPI backend.

Format:  <base64url(JSON payload)>.<base64url(HMAC-SHA256 signature)>
Payload: {"uid": user id, "ws": workspace id, "exp": expiry unix time}

The signature uses VOUCHFLOW_SECRET_KEY, so a token cannot be edited (for example to
point at another workspace) without the key. Tokens expire after TOKEN_TTL_SECONDS.
"""

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Optional

from backend.config import settings

TOKEN_TTL_SECONDS = 12 * 60 * 60  # 12 hours
_PROCESS_FALLBACK_KEY = secrets.token_bytes(32)


@dataclass(frozen=True)
class TokenData:
    user_id: int
    workspace_id: int
    expires_at: int


def _key() -> bytes:
    if settings.VOUCHFLOW_SECRET_KEY:
        return settings.VOUCHFLOW_SECRET_KEY.encode("utf-8")
    return _PROCESS_FALLBACK_KEY  # development only: changes on every restart


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(body: str) -> str:
    return _b64(hmac.new(_key(), body.encode("ascii"), hashlib.sha256).digest())


def create_token(user_id: int, workspace_id: int, ttl_seconds: int = TOKEN_TTL_SECONDS) -> str:
    payload = {"uid": int(user_id), "ws": int(workspace_id), "exp": int(time.time()) + ttl_seconds}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{body}.{_sign(body)}"


def verify_token(token: Optional[str]) -> Optional[TokenData]:
    """Returns the token data, or None if the token is missing, edited, malformed or expired."""
    if not token or token.count(".") != 1:
        return None
    body, signature = token.split(".", 1)
    if not hmac.compare_digest(signature, _sign(body)):
        return None
    try:
        payload = json.loads(_unb64(body))
        data = TokenData(int(payload["uid"]), int(payload["ws"]), int(payload["exp"]))
    except (ValueError, KeyError, TypeError):
        return None
    if data.expires_at < time.time():
        return None
    return data
