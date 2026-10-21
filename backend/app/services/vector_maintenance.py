from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AuditLog,
    Feedback,
    IntegrationRun,
    Requirement,
    RequirementVersion,
    TestCase,
    TestCaseVersion,
    VectorChunk,
)
from app.services.generation import PineconeVectorStore
from app.services.vector_backfill import enqueue_vector_backfill


@dataclass(frozen=True)
class VectorMaintenancePlan:
    expected_count: int
    remote_count: int
    missing_ids: tuple[str, ...]
    orphan_ids: tuple[str, ...]


@dataclass(frozen=True)
class VectorMaintenanceResult:
    run_id: uuid.UUID
    project_id: uuid.UUID | None
    expected_count: int
    remote_count: int
    missing_count: int
    orphan_count: int
    deleted_orphan_count: int
    repair_queued_count: int
    estimated_storage_bytes: int
    provider_stats: dict


def build_maintenance_plan(
    expected_ids: set[str],
    remote_ids: set[str],
    *,
    allow_orphan_detection: bool,
) -> VectorMaintenancePlan:
    return VectorMaintenancePlan(
        expected_count=len(expected_ids),
        remote_count=len(remote_ids),
        missing_ids=tuple(sorted(expected_ids - remote_ids)),
        orphan_ids=tuple(sorted(remote_ids - expected_ids)) if allow_orphan_detection else (),
    )

async def _expected_vector_ids(db: AsyncSession, project_id: uuid.UUID | None) -> set[str]:
    chunk_stmt = select(VectorChunk.vector_id)
    if project_id is not None:
        chunk_stmt = chunk_stmt.where(VectorChunk.project_id == project_id)
    expected = {item for item in (await db.execute(chunk_stmt)).scalars() if item}

    requirement_filters = [Requirement.project_id == project_id] if project_id is not None else []
    expected.update(
        item
        for item in (await db.execute(select(Requirement.vector_id).where(*requirement_filters))).scalars()
        if item
    )
    version_filters = [RequirementVersion.project_id == project_id] if project_id is not None else []
    expected.update(
        item
        for item in (await db.execute(select(RequirementVersion.vector_id).where(*version_filters))).scalars()
        if item
    )
    test_case_stmt = select(TestCase.vector_id).join(Requirement, Requirement.id == TestCase.requirement_id)
    version_stmt = select(TestCaseVersion.vector_id).join(
        Requirement, Requirement.id == TestCaseVersion.requirement_id
    )
    if project_id is not None:
        test_case_stmt = test_case_stmt.where(Requirement.project_id == project_id)
        version_stmt = version_stmt.where(Requirement.project_id == project_id)
    expected.update(item for item in (await db.execute(test_case_stmt)).scalars() if item)
    expected.update(item for item in (await db.execute(version_stmt)).scalars() if item)

    feedback_stmt = select(Feedback.vector_id)
    if project_id is not None:
        requirement_ids = select(Requirement.id).where(Requirement.project_id == project_id)
        feedback_stmt = feedback_stmt.where(
            Feedback.target_level == "requirement", Feedback.target_id.in_(requirement_ids)
        )
    expected.update(item for item in (await db.execute(feedback_stmt)).scalars() if item)
    return expected


async def reconcile_vectors(
    db: AsyncSession,
    store: PineconeVectorStore,
    *,
    project_id: uuid.UUID | None = None,
    repair_missing: bool = False,
    delete_orphans: bool = False,
    actor: str = "vector-maintenance",
) -> VectorMaintenanceResult:
    """Compare the durable vector inventory with Pinecone and optionally repair drift.

    Orphan deletion is deliberately limited to a full namespace audit. A project-
    scoped audit cannot prove that a vector belongs to no other project.
    """

    if delete_orphans and project_id is not None:
        raise ValueError("orphan deletion requires a full-namespace audit")
    expected_ids = await _expected_vector_ids(db, project_id)
    remote_ids = set(await store.list_vector_ids())
    plan = build_maintenance_plan(
        expected_ids,
        remote_ids,
        allow_orphan_detection=project_id is None,
    )
    deleted = 0
    if delete_orphans and plan.orphan_ids:
        for start in range(0, len(plan.orphan_ids), 100):
            batch = list(plan.orphan_ids[start : start + 100])
            await store.delete(batch)
            deleted += len(batch)

    repair_queued = 0
    if repair_missing and plan.missing_ids:
        backfill = await enqueue_vector_backfill(
            db,
            project_id=project_id,
            include_all=True,
            actor=actor,
        )
        repair_queued = backfill.queued_count + backfill.requeued_count

    stats = await store.describe_stats()
    dimension = int(stats.get("dimension") or 0)
    estimated_storage_bytes = plan.remote_count * dimension * 4
    now = datetime.now(UTC).replace(tzinfo=None)
    run = IntegrationRun(
        integration_type="vector_maintenance",
        status="completed",
        requested_by=actor,
        parameters={
            "project_id": str(project_id) if project_id else None,
            "repair_missing": repair_missing,
            "delete_orphans": delete_orphans,
        },
        result={
            **asdict(plan),
            "deleted_orphan_count": deleted,
            "repair_queued_count": repair_queued,
            "estimated_storage_bytes": estimated_storage_bytes,
            "provider_stats": stats,
        },
        completed_at=now,
    )
    db.add(run)
    await db.flush()
    db.add(
        AuditLog(
            entity_type="integration",
            entity_id=run.id,
            action="vector_maintenance_completed",
            actor=actor,
            details=run.result,
        )
    )
    await db.commit()
    return VectorMaintenanceResult(
        run_id=run.id,
        project_id=project_id,
        expected_count=plan.expected_count,
        remote_count=plan.remote_count,
        missing_count=len(plan.missing_ids),
        orphan_count=len(plan.orphan_ids),
        deleted_orphan_count=deleted,
        repair_queued_count=repair_queued,
        estimated_storage_bytes=estimated_storage_bytes,
        provider_stats=stats,
    )
