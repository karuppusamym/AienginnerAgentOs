from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .database import get_db
from .models import User
from .request_context import is_production


_DEFAULT_JWT_SECRET = "local-development-secret-change-me"
JWT_SECRET = os.getenv("JWT_SECRET", _DEFAULT_JWT_SECRET)
JWT_ALGORITHM = "HS256"
TOKEN_TTL_HOURS = 12
SESSION_COOKIE = "datapilot_session"
CSRF_HEADER_VALUE = "datapilot"
security = HTTPBearer(auto_error=False)

if is_production() and (JWT_SECRET == _DEFAULT_JWT_SECRET or len(JWT_SECRET) < 32):
    # A guessable signing key lets anyone mint admin tokens; refuse to boot.
    raise RuntimeError("JWT_SECRET must be set to a random value of at least 32 characters when APP_ENV=production")

# Endpoints a user who must change their password can still reach.
_PASSWORD_CHANGE_ALLOWED = {"/auth/me", "/auth/change-password", "/auth/logout"}
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 210_000)
    return f"pbkdf2_sha256$210000${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def create_access_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user.id,
        "email": user.email,
        "role": user.role,
        "iat": now,
        "exp": now + timedelta(hours=TOKEN_TTL_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    token = credentials.credentials if credentials is not None else request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in required")
    if credentials is None and request.method not in _SAFE_METHODS and request.headers.get("X-Requested-With") != CSRF_HEADER_VALUE:
        # Cookie sessions are sent by the browser automatically; a custom header
        # cannot be added cross-site without CORS approval, which blocks CSRF.
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing X-Requested-With header for cookie session")
    try:
        payload = jwt.decode(
            token, JWT_SECRET, algorithms=[JWT_ALGORITHM]
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session"
        ) from exc
    user = db.get(User, payload.get("sub"))
    if user is None or not user.active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User unavailable")
    if user.must_change_password and is_production() and request.url.path not in _PASSWORD_CHANGE_ALLOWED:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Password change required before continuing")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return user
