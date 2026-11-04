"""
Password hashing with bcrypt.

Only the hash is stored (users.password_hash). bcrypt adds a random salt to every hash,
so two users with the same password still get different hashes, and checking a password
takes a deliberate fraction of a second (slows down guessing).
"""

import bcrypt

BCRYPT_ROUNDS = 12
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_BYTES = 72  # bcrypt only uses the first 72 bytes


def _to_bytes(password: str) -> bytes:
    data = (password or "").encode("utf-8")
    if len(data) > MAX_PASSWORD_BYTES:
        raise ValueError(f"Password is too long (maximum {MAX_PASSWORD_BYTES} bytes).")
    return data


def hash_password(password: str) -> str:
    """Returns a bcrypt hash like '$2b$12$...'. Never returns or stores the plain password."""
    return bcrypt.hashpw(_to_bytes(password), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    """True if the password matches the stored hash. Never raises on bad input."""
    try:
        return bcrypt.checkpw(_to_bytes(password), (password_hash or "").encode("ascii"))
    except (ValueError, TypeError):
        return False
