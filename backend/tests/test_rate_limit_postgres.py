import asyncio
import os
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.models import ApiRateLimit
from app.services.rate_limit import consume_rate_limit


TEST_DSN = os.getenv("TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not TEST_DSN, reason="TEST_POSTGRES_DSN is not configured")


def test_shared_rate_limit_is_atomic_per_hashed_subject_bucket() -> None:
    async def scenario() -> None:
        engine = create_async_engine(TEST_DSN)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        scope = f"rate-test-{uuid.uuid4()}"
        config = Settings(_env_file=None, rate_limit_enabled=True)
        try:
            async with session_factory() as db:
                assert await consume_rate_limit(
                    db, scope=scope, subject="client-a", limit=2, config=config
                ) == 1
                assert await consume_rate_limit(
                    db, scope=scope, subject="client-a", limit=2, config=config
                ) == 2
                with pytest.raises(HTTPException) as exc_info:
                    await consume_rate_limit(db, scope=scope, subject="client-a", limit=2, config=config)
                assert exc_info.value.status_code == 429
                assert exc_info.value.headers == {"Retry-After": "60"}
                assert await consume_rate_limit(
                    db, scope=scope, subject="client-b", limit=2, config=config
                ) == 1
        finally:
            async with session_factory() as db:
                await db.execute(delete(ApiRateLimit).where(ApiRateLimit.bucket_key.like(f"{scope}:%")))
                await db.commit()
            await engine.dispose()

    asyncio.run(scenario())


def test_disabled_rate_limit_does_not_write_a_counter() -> None:
    async def scenario() -> None:
        engine = create_async_engine(TEST_DSN)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as db:
            count = await consume_rate_limit(
                db,
                scope=f"disabled-{uuid.uuid4()}",
                subject="client",
                limit=1,
                config=Settings(_env_file=None, rate_limit_enabled=False),
            )
            assert count == 0
        await engine.dispose()

    asyncio.run(scenario())
