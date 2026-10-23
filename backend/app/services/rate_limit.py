from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import case
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, settings
from app.core.security import Principal, authenticate_request
from app.db import get_db
from app.models import ApiRateLimit


def _window_start(now: datetime) -> datetime:
    return now.astimezone(UTC).replace(second=0, microsecond=0)


def _bucket_key(scope: str, subject: str) -> str:
    digest = hashlib.sha256(f"{scope}:{subject}".encode("utf-8")).hexdigest()
    return f"{scope}:{digest}"


async def consume_rate_limit(
    db: AsyncSession,
    *,
    scope: str,
    subject: str,
    limit: int,
    config: Settings = settings,
) -> int:
    if not config.rate_limit_enabled:
        return 0
    if limit < 1:
        raise RuntimeError("rate limit must be positive")
    window = _window_start(datetime.now(UTC))
    key = _bucket_key(scope, subject)
    statement = insert(ApiRateLimit).values(bucket_key=key, window_start=window, request_count=1)
    reset_window = ApiRateLimit.window_start < window
    statement = statement.on_conflict_do_update(
        index_elements=[ApiRateLimit.bucket_key],
        set_={
            "window_start": case((reset_window, window), else_=ApiRateLimit.window_start),
            "request_count": case((reset_window, 1), else_=ApiRateLimit.request_count + 1),
        },
    ).returning(ApiRateLimit.request_count)
    count = await db.scalar(statement)
    await db.commit()
    if count is None:
        raise RuntimeError("rate limit counter did not return a value")
    if count > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Request rate limit exceeded",
            headers={"Retry-After": "60"},
        )
    return count


async def enforce_authenticated_rate_limit(
    principal: Principal = Depends(authenticate_request),
    db: AsyncSession = Depends(get_db),
) -> None:
    await consume_rate_limit(
        db,
        scope="api-user",
        subject=str(principal.user_id),
        limit=settings.api_rate_limit_per_minute,
    )


async def enforce_auth_rate_limit(request: Request, db: AsyncSession, *, scope: str) -> None:
    client_host = request.client.host if request.client else "unknown"
    await consume_rate_limit(
        db,
        scope=scope,
        subject=client_host,
        limit=settings.auth_rate_limit_per_minute,
    )
