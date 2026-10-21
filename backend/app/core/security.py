from __future__ import annotations

import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jwt import InvalidTokenError
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db import get_db
from app.models import User


GLOBAL_ROLES = {"reviewer", "approver", "admin"}
password_hash = PasswordHash.recommended()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    username: str
    role: str
    token_version: int


_principal_context: ContextVar[Principal | None] = ContextVar("principal", default=None)


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("password must contain at least 12 characters")
    return password_hash.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    try:
        return password_hash.verify(password, encoded)
    except (TypeError, ValueError):
        return False


def create_access_token(user: User) -> tuple[str, int]:
    if len(settings.auth_jwt_secret) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured: AUTH_JWT_SECRET must be at least 32 characters",
        )
    now = datetime.now(timezone.utc)
    lifetime = timedelta(minutes=settings.auth_access_token_minutes)
    claims = {
        "sub": str(user.id),
        "ver": user.token_version,
        "iat": now,
        "nbf": now,
        "exp": now + lifetime,
        "iss": settings.auth_issuer,
        "aud": settings.auth_audience,
    }
    token = jwt.encode(claims, settings.auth_jwt_secret, algorithm=settings.auth_jwt_algorithm)
    return token, int(lifetime.total_seconds())


async def authenticate_request(
    request: Request,
    bearer_token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> Principal:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired access token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if len(settings.auth_jwt_secret) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured",
        )
    cookie_token = request.cookies.get(settings.auth_cookie_name)
    token = bearer_token or cookie_token
    if not token:
        raise credentials_error
    if cookie_token and not bearer_token and request.method not in {"GET", "HEAD", "OPTIONS"}:
        allowed_origins = {
            origin.strip() for origin in settings.auth_allowed_origins.split(",") if origin.strip()
        }
        if request.headers.get("origin") not in allowed_origins:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid request origin")
    try:
        claims = jwt.decode(
            token,
            settings.auth_jwt_secret,
            algorithms=[settings.auth_jwt_algorithm],
            audience=settings.auth_audience,
            issuer=settings.auth_issuer,
            options={"require": ["sub", "ver", "iat", "nbf", "exp", "iss", "aud"]},
        )
        user_id = uuid.UUID(claims["sub"])
        token_version = int(claims["ver"])
    except (InvalidTokenError, KeyError, TypeError, ValueError):
        raise credentials_error

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user or not user.active or user.token_version != token_version or user.role not in GLOBAL_ROLES:
        raise credentials_error

    principal = Principal(
        user_id=user.id,
        username=user.username,
        role=user.role,
        token_version=user.token_version,
    )
    _principal_context.set(principal)
    return principal


def current_principal() -> Principal:
    principal = _principal_context.get()
    if principal is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return principal


def require_global_role(*allowed_roles: str) -> Principal:
    principal = current_principal()
    if principal.role not in allowed_roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role for this action")
    return principal
