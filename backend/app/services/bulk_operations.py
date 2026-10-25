from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, settings
from app.core.security import Principal, principal_context
from app.models import BulkOperationJob


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class BulkOperationProcessor:
    """Restart-safe processor for requirement-level bulk operations."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        config: Settings = settings,
        worker_id: str | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._config = config
        self._worker_id = worker_id or f"bulk-operation-{uuid.uuid4()}"

    async def process_batch(self) -> uuid.UUID | None:
        job_id = await self._claim()
        if job_id is None:
            return None

        async with self._session_factory() as db:
            job = await db.get(BulkOperationJob, job_id, with_for_update=True)
            if not job or job.status != "processing" or job.locked_by != self._worker_id:
                return job_id

            items = list((job.result or {}).get("items", []))
            next_item = next((item for item in items if item.get("status") in {"queued", "processing"}), None)
            if next_item is None:
                self._finish(job, items)
                await db.commit()
                return job_id

            next_item["status"] = "processing"
            job.result = {"items": items}
            await db.commit()

            actor = job.requested_by
            principal = Principal(user_id=uuid.UUID(int=0), username=actor, role="app_admin", token_version=0)
            try:
                # Calling the existing single-item route functions keeps the
                # synchronous and queued paths behaviorally identical. The
                # system principal is scoped to this one worker operation.
                from app.api.routes import generate_requirement_draft, get_requirement_impact

                with principal_context(principal):
                    if job.operation_type == "generate_test_cases":
                        await generate_requirement_draft(str(next_item["requirement_id"]), db)
                    elif job.operation_type == "impact_analysis":
                        await get_requirement_impact(str(next_item["requirement_id"]), db)
                    else:
                        raise ValueError(f"Unsupported bulk operation: {job.operation_type}")
                next_item["status"] = "completed"
                next_item["message"] = None
                job.completed_count += 1
            except Exception as exc:  # one bad requirement must not stop the batch
                next_item["status"] = "failed"
                next_item["message"] = self._error_message(exc)
                job.failed_count += 1
                job.last_error_type = type(exc).__name__

            job.result = {"items": items}
            job.locked_at = None
            job.locked_by = None
            if job.completed_count + job.failed_count >= job.total_count:
                job.status = "completed" if job.completed_count else "failed"
                job.completed_at = _utcnow()
            else:
                job.status = "queued"
            await db.commit()
        return job_id

    async def _claim(self) -> uuid.UUID | None:
        stale_before = _utcnow() - timedelta(seconds=self._config.outbox_lock_timeout_seconds)
        async with self._session_factory() as db:
            job = (
                await db.execute(
                    select(BulkOperationJob)
                    .where(
                        (BulkOperationJob.status == "queued")
                        | (
                            (BulkOperationJob.status == "processing")
                            & (BulkOperationJob.locked_at < stale_before)
                        )
                    )
                    .order_by(BulkOperationJob.created_at.asc())
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
            ).scalars().first()
            if not job:
                return None
            job.status = "processing"
            job.locked_at = _utcnow()
            job.locked_by = self._worker_id
            await db.commit()
            return job.id

    @staticmethod
    def _finish(job: BulkOperationJob, items: list[dict]) -> None:
        job.result = {"items": items}
        job.locked_at = None
        job.locked_by = None
        job.status = "completed" if job.completed_count else "failed"
        job.completed_at = _utcnow()

    @staticmethod
    def _error_message(exc: Exception) -> str:
        if isinstance(exc, HTTPException):
            return str(exc.detail)
        return str(exc)[:500] or type(exc).__name__
