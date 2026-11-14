"""Password hashing and JWT token helpers."""
from __future__ import annotations

import time
import uuid
from typing import Any

import bcrypt
from jose import JWTError, jwt

from app.config import get_settings
from app.core.exceptions import UnauthorizedError

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_BYTES = 72  # bcrypt limit


def validate_password_strength(password: str) -> None:
    if len(password) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"Password must be at least {PASSWORD_MIN_LENGTH} characters")
    if len(password.encode("utf-8")) > PASSWORD_MAX_BYTES:
        raise ValueError("Password is too long (maximum 72 UTF-8 bytes)")


def hash_password(password: str) -> str:
    validate_password_strength(password)
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(
    subject: str,
    role: str,
    *,
    extra_claims: dict[str, Any] | None = None,
    expires_minutes: int | None = None,
) -> str:
    settings = get_settings()
    now = int(time.time())
    expire = now + (expires_minutes or settings.access_token_expire_minutes) * 60
    payload: dict[str, Any] = {
        "sub": str(subject),
        "role": role,
        "type": "access",
        "iat": now,
        "nbf": now,
        "exp": expire,
        "jti": str(uuid.uuid4()),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"verify_aud": False},
        )
    except JWTError as exc:
        raise UnauthorizedError("Invalid or expired authentication token") from exc
    if payload.get("type") != "access":
        raise UnauthorizedError("Invalid token type")
    if not payload.get("sub"):
        raise UnauthorizedError("Token is missing a subject")
    if payload.get("role") not in {"student", "admin"}:
        raise UnauthorizedError("Token has an invalid role")
    return payload
