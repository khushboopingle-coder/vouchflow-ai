"""
Test helpers (Phase 2): throw-away users with their own private workspace.

    with temp_user() as user:          # user.ids[1] = the user's copy of sample invoice 1
        client.get(f"/invoices/{user.ids[1]}", headers=user.headers)

Everything (workspace, data, audit logs, login) is deleted when the block ends.
"""

import contextlib
import uuid
from types import SimpleNamespace

from backend.auth.tokens import create_token
from backend.database.db import SessionLocal, init_db
from backend.services import auth_service, workspace_service

TEST_PASSWORD = "correct-horse-battery"


@contextlib.contextmanager
def temp_user(load_sample: bool = True, password: str = TEST_PASSWORD):
    init_db()
    db = SessionLocal()
    email = f"pytest-{uuid.uuid4().hex[:10]}@example.com"
    account = auth_service.signup(db, email, password, load_sample=False)
    try:
        maps = (workspace_service.load_sample_data(db, account.workspace_id, who=email)
                if load_sample else {"invoices": {}})
    except Exception:
        workspace_service.delete_workspace(db, account.workspace_id)  # clean up even if setup fails
        db.close()
        raise
    user = SimpleNamespace(
        account=account,
        email=email,
        password=password,
        user_id=account.user_id,
        workspace_id=account.workspace_id,
        headers={"Authorization": f"Bearer {create_token(account.user_id, account.workspace_id)}"},
        ids=maps["invoices"],
        session_auth={"user_id": account.user_id, "email": email,
                      "workspace_id": account.workspace_id, "workspace_name": account.workspace_name},
    )
    try:
        yield user
    finally:
        workspace_service.delete_workspace(db, account.workspace_id)
        db.close()
