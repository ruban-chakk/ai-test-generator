from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AuditLog,
    Feedback,
    IntegrationRun,
    KnowledgeDocument,
    OutboxEvent,
    Requirement,
    RequirementVersion,
    TestCase,
    TestCaseVersion,
    TestScenario,
)
from app.services.outbox import (
    FEEDBACK_INDEX_REQUESTED,
    KNOWLEDGE_DOCUMENT_INDEX_REQUESTED,
    REQUIREMENT_INDEX_REQUESTED,
    REQUIREMENT_VERSION_INDEX_REQUESTED,
    TEST_CASE_INDEX_REQUESTED,
    TEST_CASE_VERSION_INDEX_REQUESTED,
    enqueue_index_event,
)


@dataclass(frozen=True)
class VectorBackfillResult:
    run_id: uuid.UUID
    candidate_count: int
    queued_count: int
    requeued_count: int
    in_flight_count: int
    requirement_count: int
    requirement_version_count: int
    test_case_count: int
    test_case_version_count: int
    feedback_count: int
    knowledge_document_count: int


@dataclass(frozen=True)
class _Candidate:
    event_type: str
    aggregate_type: str
    aggregate_id: uuid.UUID
    event_key: str


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def enqueue_vector_backfill(
    db: AsyncSession,
    *,
    project_id: uuid.UUID | None = None,
    include_all: bool = False,
    actor: str = "vector-backfill-cli",
) -> VectorBackfillResult:
    """Queue missing or explicitly requested vectors without calling providers in the DB transaction."""

    requirement_version_completed = exists(
        select(OutboxEvent.id).where(
            OutboxEvent.event_type == REQUIREMENT_VERSION_INDEX_REQUESTED,
            OutboxEvent.aggregate_id == RequirementVersion.id,
            OutboxEvent.status == "completed",
        )
    )
    requirement_versions_stmt = select(RequirementVersion).where(
        RequirementVersion.project_id.is_not(None)
    )
    if project_id is not None:
        requirement_versions_stmt = requirement_versions_stmt.where(
            RequirementVersion.project_id == project_id
        )
    if not include_all:
        requirement_versions_stmt = requirement_versions_stmt.where(
            or_(RequirementVersion.vector_id.is_(None), ~requirement_version_completed)
        )
    requirement_versions = list((await db.execute(requirement_versions_stmt)).scalars().all())
    requirement_version_ids = {version.requirement_id for version in requirement_versions}
    versioned_requirements = (
        list(
            (
                await db.execute(
                    select(Requirement).where(Requirement.id.in_(requirement_version_ids))
                )
            ).scalars().all()
        )
        if requirement_version_ids
        else []
    )
    requirement_by_id = {requirement.id: requirement for requirement in versioned_requirements}

    requirement_completed = exists(
        select(OutboxEvent.id).where(
            OutboxEvent.event_type == REQUIREMENT_INDEX_REQUESTED,
            OutboxEvent.aggregate_id == Requirement.id,
            OutboxEvent.status == "completed",
        )
    )
    current_requirement_version_exists = exists(
        select(RequirementVersion.id).where(
            RequirementVersion.requirement_id == Requirement.id,
            RequirementVersion.version == Requirement.version,
        )
    )
    requirements_stmt = select(Requirement).where(
        Requirement.project_id.is_not(None),
        ~current_requirement_version_exists,
    )
    if project_id is not None:
        requirements_stmt = requirements_stmt.where(Requirement.project_id == project_id)
    if not include_all:
        requirements_stmt = requirements_stmt.where(
            or_(Requirement.vector_id.is_(None), ~requirement_completed)
        )
    requirements = list((await db.execute(requirements_stmt)).scalars().all())

    version_completed = exists(
        select(OutboxEvent.id).where(
            OutboxEvent.event_type == TEST_CASE_VERSION_INDEX_REQUESTED,
            OutboxEvent.aggregate_id == TestCaseVersion.id,
            OutboxEvent.status == "completed",
        )
    )
    test_case_versions_stmt = (
        select(TestCaseVersion)
        .join(Requirement, Requirement.id == TestCaseVersion.requirement_id)
    )
    if project_id is not None:
        test_case_versions_stmt = test_case_versions_stmt.where(Requirement.project_id == project_id)
    if not include_all:
        test_case_versions_stmt = test_case_versions_stmt.where(
            or_(TestCaseVersion.vector_id.is_(None), ~version_completed)
        )
    test_case_versions = list((await db.execute(test_case_versions_stmt)).scalars().all())
    version_case_ids = {version.test_case_id for version in test_case_versions}
    version_cases = (
        list(
            (
                await db.execute(select(TestCase).where(TestCase.id.in_(version_case_ids)))
            ).scalars().all()
        )
        if version_case_ids
        else []
    )
    version_case_by_id = {test_case.id: test_case for test_case in version_cases}

    test_cases_stmt = (
        select(TestCase)
        .join(Requirement, Requirement.id == TestCase.requirement_id)
    )
    if project_id is not None:
        test_cases_stmt = test_cases_stmt.where(Requirement.project_id == project_id)
    if not include_all:
        current_search_projection_completed = exists(
            select(OutboxEvent.id).where(
                OutboxEvent.event_type == TEST_CASE_INDEX_REQUESTED,
                OutboxEvent.aggregate_id == TestCase.id,
                OutboxEvent.event_key == func.concat(
                    "test_case.current_index:",
                    TestCase.id,
                    ":v",
                    TestCase.version,
                    ":",
                    TestCase.status,
                ),
                OutboxEvent.status == "completed",
            )
        )
        test_cases_stmt = test_cases_stmt.where(~current_search_projection_completed)
    test_cases = list((await db.execute(test_cases_stmt)).scalars().all())

    feedback_completed = exists(
        select(OutboxEvent.id).where(
            OutboxEvent.event_type == FEEDBACK_INDEX_REQUESTED,
            OutboxEvent.aggregate_id == Feedback.id,
            OutboxEvent.status == "completed",
        )
    )
    feedback_stmt = select(Feedback)
    if not include_all:
        feedback_stmt = feedback_stmt.where(or_(Feedback.vector_id.is_(None), ~feedback_completed))
    if project_id is not None:
        requirement_ids = select(Requirement.id).where(Requirement.project_id == project_id)
        scenario_ids = (
            select(TestScenario.id)
            .join(Requirement, Requirement.id == TestScenario.requirement_id)
            .where(Requirement.project_id == project_id)
        )
        test_case_ids = (
            select(TestCase.id)
            .join(Requirement, Requirement.id == TestCase.requirement_id)
            .where(Requirement.project_id == project_id)
        )
        feedback_stmt = feedback_stmt.where(
            or_(
                and_(Feedback.target_level.in_({"requirement", "suite"}), Feedback.target_id.in_(requirement_ids)),
                and_(Feedback.target_level == "scenario", Feedback.target_id.in_(scenario_ids)),
                and_(Feedback.target_level == "test_case", Feedback.target_id.in_(test_case_ids)),
            )
        )
    feedback_items = list((await db.execute(feedback_stmt)).scalars().all())

    knowledge_completed = exists(
        select(OutboxEvent.id).where(
            OutboxEvent.event_type == KNOWLEDGE_DOCUMENT_INDEX_REQUESTED,
            OutboxEvent.aggregate_id == KnowledgeDocument.id,
            OutboxEvent.status == "completed",
        )
    )
    knowledge_stmt = select(KnowledgeDocument)
    if project_id is not None:
        knowledge_stmt = knowledge_stmt.where(KnowledgeDocument.project_id == project_id)
    if not include_all:
        knowledge_stmt = knowledge_stmt.where(
            or_(KnowledgeDocument.vector_id.is_(None), ~knowledge_completed)
        )
    knowledge_documents = list((await db.execute(knowledge_stmt)).scalars().all())

    candidates: list[_Candidate] = []
    for requirement in requirements:
        requirement.vector_id = f"requirement:{requirement.id}:v{requirement.version}"
        candidates.append(
            _Candidate(
                event_type=REQUIREMENT_INDEX_REQUESTED,
                aggregate_type="requirement",
                aggregate_id=requirement.id,
                event_key=f"vector.reconcile:requirement:{requirement.id}",
            )
        )
    for version in requirement_versions:
        version.vector_id = version.vector_id or f"requirement:{version.requirement_id}:v{version.version}"
        current = requirement_by_id.get(version.requirement_id)
        if current and current.version == version.version:
            current.vector_id = version.vector_id
        candidates.append(
            _Candidate(
                event_type=REQUIREMENT_VERSION_INDEX_REQUESTED,
                aggregate_type="requirement_version",
                aggregate_id=version.id,
                event_key=f"vector.reconcile:requirement_version:{version.id}",
            )
        )
    for test_case in test_cases:
        candidates.append(
            _Candidate(
                event_type=TEST_CASE_INDEX_REQUESTED,
                aggregate_type="test_case",
                aggregate_id=test_case.id,
                event_key=(
                    f"test_case.current_index:{test_case.id}:v{test_case.version}:"
                    f"{test_case.status}"
                ),
            )
        )
    for version in test_case_versions:
        version.vector_id = version.vector_id or f"test_case:{version.test_case_id}:v{version.version}"
        current = version_case_by_id.get(version.test_case_id)
        if current and current.version == version.version:
            current.vector_id = version.vector_id
            if current.repository_status != "indexed":
                current.repository_status = "pending_index"
                current.repository_synced_at = None
        candidates.append(
            _Candidate(
                event_type=TEST_CASE_VERSION_INDEX_REQUESTED,
                aggregate_type="test_case_version",
                aggregate_id=version.id,
                event_key=f"vector.reconcile:test_case_version:{version.id}",
            )
        )
    for feedback in feedback_items:
        feedback.vector_id = feedback.vector_id or f"feedback:{feedback.id}"
        candidates.append(
            _Candidate(
                event_type=FEEDBACK_INDEX_REQUESTED,
                aggregate_type="feedback",
                aggregate_id=feedback.id,
                event_key=f"vector.reconcile:feedback:{feedback.id}",
            )
        )
    for document in knowledge_documents:
        document.vector_id = document.vector_id or f"knowledge_document:{document.id}"
        document.status = "pending_index"
        candidates.append(
            _Candidate(
                event_type=KNOWLEDGE_DOCUMENT_INDEX_REQUESTED,
                aggregate_type="knowledge_document",
                aggregate_id=document.id,
                event_key=f"vector.reconcile:knowledge_document:{document.id}",
            )
        )

    existing_by_aggregate: dict[tuple[str, uuid.UUID], list[OutboxEvent]] = {}
    if candidates:
        event_filters = [
            and_(
                OutboxEvent.event_type == candidate.event_type,
                OutboxEvent.aggregate_id == candidate.aggregate_id,
            )
            for candidate in candidates
        ]
        existing_events = list(
            (
                await db.execute(
                    select(OutboxEvent)
                    .where(or_(*event_filters))
                    .order_by(OutboxEvent.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        for event in existing_events:
            existing_by_aggregate.setdefault((event.event_type, event.aggregate_id), []).append(event)

    queued_count = 0
    requeued_count = 0
    in_flight_count = 0
    now = _utcnow()
    for candidate in candidates:
        existing = existing_by_aggregate.get((candidate.event_type, candidate.aggregate_id), [])
        active = next((event for event in existing if event.status in {"pending", "processing"}), None)
        if active is not None:
            in_flight_count += 1
            continue
        reusable = existing[0] if existing else None
        if reusable is not None:
            reusable.status = "pending"
            reusable.attempts = 0
            reusable.available_at = now
            reusable.locked_at = None
            reusable.locked_by = None
            reusable.processed_at = None
            reusable.last_error = None
            requeued_count += 1
            continue
        enqueue_index_event(
            db,
            event_key=candidate.event_key,
            event_type=candidate.event_type,
            aggregate_type=candidate.aggregate_type,
            aggregate_id=candidate.aggregate_id,
        )
        queued_count += 1

    run = IntegrationRun(
        integration_type="vector_backfill",
        status="completed",
        requested_by=actor,
        parameters={
            "project_id": str(project_id) if project_id else None,
            "include_all": include_all,
        },
        result={
            "candidate_count": len(candidates),
            "queued_count": queued_count,
            "requeued_count": requeued_count,
            "in_flight_count": in_flight_count,
            "requirement_count": len(requirements),
            "requirement_version_count": len(requirement_versions),
            "test_case_count": len(test_cases),
            "test_case_version_count": len(test_case_versions),
            "feedback_count": len(feedback_items),
            "knowledge_document_count": len(knowledge_documents),
        },
        completed_at=now,
    )
    db.add(run)
    await db.flush()
    db.add(
        AuditLog(
            entity_type="integration",
            entity_id=run.id,
            action="vector_backfill_queued",
            actor=actor,
            details={
                "project_id": str(project_id) if project_id else None,
                "include_all": include_all,
                "candidate_count": len(candidates),
                "queued_count": queued_count,
                "requeued_count": requeued_count,
                "in_flight_count": in_flight_count,
            },
        )
    )
    await db.commit()
    return VectorBackfillResult(
        run_id=run.id,
        candidate_count=len(candidates),
        queued_count=queued_count,
        requeued_count=requeued_count,
        in_flight_count=in_flight_count,
        requirement_count=len(requirements),
        requirement_version_count=len(requirement_versions),
        test_case_count=len(test_cases),
        test_case_version_count=len(test_case_versions),
        feedback_count=len(feedback_items),
        knowledge_document_count=len(knowledge_documents),
    )
