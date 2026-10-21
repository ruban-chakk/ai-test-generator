from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.core.config import Settings, settings
from app.models import (
    Feedback,
    OutboxEvent,
    RepositorySyncRun,
    Requirement,
    TestCase,
    TestExecutionRun,
    TestScenario,
)
from app.services.execution import ExecutableTestCase, ExecutionResult, TestExecutionClient
from app.services.integrations import RepositoryClient, RepositoryTestCase, build_test_repository_client
from app.services.indexing import IndexableArtifact, IndexingService, build_indexing_service


TEST_CASE_INDEX_REQUESTED = "test_case.index_requested"
FEEDBACK_INDEX_REQUESTED = "feedback.index_requested"
REQUIREMENT_INDEX_REQUESTED = "requirement.index_requested"
TEST_CASE_REPOSITORY_SYNC_REQUESTED = "test_case.repository_sync_requested"
TEST_CASE_EXECUTION_REQUESTED = "test_case.execution_requested"


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def enqueue_outbox_event(
    db: AsyncSession,
    *,
    event_key: str,
    event_type: str,
    aggregate_type: str,
    aggregate_id: uuid.UUID,
    payload: dict | None = None,
) -> OutboxEvent:
    event = OutboxEvent(
        event_key=event_key,
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload={"schema_version": 1, **(payload or {})},
        status="pending",
    )
    db.add(event)
    return event


def enqueue_index_event(
    db: AsyncSession,
    *,
    event_key: str,
    event_type: str,
    aggregate_type: str,
    aggregate_id: uuid.UUID,
) -> OutboxEvent:
    return enqueue_outbox_event(
        db,
        event_key=event_key,
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
    )


class OutboxProcessor:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        indexing_service: IndexingService | None = None,
        config: Settings = settings,
        worker_id: str | None = None,
        repository_client: RepositoryClient | None = None,
        execution_client: TestExecutionClient | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._indexing_service = indexing_service
        self._repository_client = repository_client
        self._execution_client = execution_client
        self._config = config
        self._worker_id = worker_id or f"indexer-{uuid.uuid4()}"

    async def process_batch(self) -> int:
        event_ids = await self._claim_batch()
        for event_id in event_ids:
            await self._process_claimed_event(event_id)
        return len(event_ids)

    async def _claim_batch(self) -> list[uuid.UUID]:
        now = _utcnow()
        stale_before = now - timedelta(seconds=self._config.outbox_lock_timeout_seconds)
        async with self._session_factory() as db:
            result = await db.execute(
                select(OutboxEvent)
                .where(
                    OutboxEvent.attempts < self._config.outbox_max_attempts,
                    OutboxEvent.available_at <= now,
                    or_(
                        OutboxEvent.status == "pending",
                        (OutboxEvent.status == "processing") & (OutboxEvent.locked_at < stale_before),
                    ),
                )
                .order_by(OutboxEvent.created_at.asc())
                .limit(self._config.outbox_batch_size)
                .with_for_update(skip_locked=True)
            )
            events = result.scalars().all()
            for event in events:
                event.status = "processing"
                event.locked_at = now
                event.locked_by = self._worker_id
                event.attempts += 1
            await db.commit()
            return [event.id for event in events]

    async def _process_claimed_event(self, event_id: uuid.UUID) -> None:
        execution_result: ExecutionResult | None = None
        try:
            async with self._session_factory() as db:
                event = await db.get(OutboxEvent, event_id)
                if not event or event.status != "processing" or event.locked_by != self._worker_id:
                    return
                if event.event_type in {
                    REQUIREMENT_INDEX_REQUESTED,
                    TEST_CASE_INDEX_REQUESTED,
                    FEEDBACK_INDEX_REQUESTED,
                }:
                    operation = ("index", await self._load_artifact(db, event))
                elif event.event_type == TEST_CASE_REPOSITORY_SYNC_REQUESTED:
                    operation = ("repository", await self._load_repository_delivery(db, event))
                elif event.event_type == TEST_CASE_EXECUTION_REQUESTED:
                    operation = ("execution", await self._load_execution(db, event))
                else:
                    raise ValueError("unsupported outbox event type")
            if operation[0] == "index":
                if self._indexing_service is None:
                    self._indexing_service = build_indexing_service(self._config)
                await self._indexing_service.index(operation[1])
            elif operation[0] == "repository":
                if self._repository_client is None:
                    self._repository_client = build_test_repository_client(self._config)
                test_case, repository, branch, idempotency_key = operation[1]
                await self._repository_client.upsert(
                    test_case,
                    repository=repository,
                    branch=branch,
                    idempotency_key=idempotency_key,
                )
            else:
                if self._execution_client is None:
                    self._execution_client = TestExecutionClient(self._config)
                test_case, environment, idempotency_key = operation[1]
                execution_result = await self._execution_client.execute(
                    test_case,
                    environment=environment,
                    idempotency_key=idempotency_key,
                )
        except Exception as exc:
            await self._record_failure(event_id, type(exc).__name__)
            return

        async with self._session_factory() as db:
            event = await db.get(OutboxEvent, event_id, with_for_update=True)
            if not event or event.status != "processing" or event.locked_by != self._worker_id:
                return
            event.status = "completed"
            event.processed_at = _utcnow()
            event.locked_at = None
            event.locked_by = None
            event.last_error = None
            if event.event_type == REQUIREMENT_INDEX_REQUESTED:
                requirement = await db.get(Requirement, event.aggregate_id)
                if requirement:
                    requirement.vector_id = requirement.vector_id or f"requirement:{requirement.id}"
            elif event.event_type == TEST_CASE_INDEX_REQUESTED:
                test_case = await db.get(TestCase, event.aggregate_id)
                if test_case:
                    test_case.repository_status = "indexed"
                    test_case.repository_synced_at = event.processed_at
            elif event.event_type == TEST_CASE_REPOSITORY_SYNC_REQUESTED:
                await self._complete_repository_delivery(db, event)
            elif event.event_type == TEST_CASE_EXECUTION_REQUESTED and execution_result is not None:
                await self._complete_execution(db, event, execution_result)
            await db.commit()

    async def _record_failure(self, event_id: uuid.UUID, error_type: str) -> None:
        async with self._session_factory() as db:
            event = await db.get(OutboxEvent, event_id, with_for_update=True)
            if not event or event.locked_by != self._worker_id:
                return
            exhausted = event.attempts >= self._config.outbox_max_attempts
            event.status = "failed" if exhausted else "pending"
            event.available_at = _utcnow() + timedelta(seconds=min(2 ** event.attempts, 300))
            event.locked_at = None
            event.locked_by = None
            event.last_error = error_type[:255]
            if exhausted and event.event_type == TEST_CASE_REPOSITORY_SYNC_REQUESTED:
                sync_run_id = event.payload.get("sync_run_id")
                if sync_run_id:
                    try:
                        parsed_sync_run_id = uuid.UUID(sync_run_id)
                    except (TypeError, ValueError, AttributeError):
                        parsed_sync_run_id = None
                    sync_run = await db.get(RepositorySyncRun, parsed_sync_run_id) if parsed_sync_run_id else None
                    if sync_run:
                        sync_run.status = "failed"
                        sync_run.completed_at = _utcnow()
                        sync_run.details = {
                            **(sync_run.details or {}),
                            "failure_type": error_type[:255],
                        }
            if exhausted and event.event_type == TEST_CASE_EXECUTION_REQUESTED:
                execution_run = await db.get(TestExecutionRun, event.aggregate_id)
                if execution_run:
                    execution_run.status = "error"
                    execution_run.completed_at = _utcnow()
                    execution_run.result = {"failure_type": error_type[:255]}
            await db.commit()

    async def _load_artifact(self, db: AsyncSession, event: OutboxEvent) -> IndexableArtifact:
        if event.event_type == REQUIREMENT_INDEX_REQUESTED:
            requirement = await db.get(Requirement, event.aggregate_id)
            if not requirement or not requirement.project_id:
                raise LookupError("requirement project is unavailable")
            return IndexableArtifact(
                vector_id=requirement.vector_id or f"requirement:{requirement.id}",
                entity_type="requirement",
                entity_id=str(requirement.id),
                project_id=str(requirement.project_id),
                text=f"Title: {requirement.title}\nDescription: {requirement.description}",
                metadata={
                    "requirement_id": str(requirement.id),
                    "external_id": requirement.external_id or "",
                    "source": requirement.source,
                    "status": requirement.status,
                },
            )

        if event.event_type == TEST_CASE_INDEX_REQUESTED:
            result = await db.execute(
                select(TestCase)
                .where(TestCase.id == event.aggregate_id)
                .options(selectinload(TestCase.steps))
            )
            test_case = result.scalars().first()
            if not test_case:
                raise LookupError("test case no longer exists")
            requirement = await db.get(Requirement, test_case.requirement_id)
            if not requirement or not requirement.project_id:
                raise LookupError("test case project is unavailable")
            step_text = " ".join(
                f"Step {step.step_number}: {step.action} Expected: {step.expected_result}"
                for step in sorted(test_case.steps, key=lambda item: item.step_number)
            )
            text = " ".join(
                part
                for part in [
                    test_case.title,
                    test_case.description,
                    test_case.prerequisite,
                    step_text,
                ]
                if part
            )
            return IndexableArtifact(
                vector_id=test_case.vector_id or f"test_case:{test_case.id}:v{test_case.version}",
                entity_type="test_case",
                entity_id=str(test_case.id),
                project_id=str(requirement.project_id),
                text=text,
                metadata={
                    "requirement_id": str(test_case.requirement_id),
                    "scenario_id": str(test_case.scenario_id),
                    "title": test_case.title,
                    "status": test_case.status,
                    "repository_status": "indexed",
                    "version": test_case.version,
                    "priority": test_case.priority or "",
                    "severity": test_case.severity or "",
                    "category": test_case.category or "",
                    "type": test_case.type or "",
                },
            )

        if event.event_type == FEEDBACK_INDEX_REQUESTED:
            feedback = await db.get(Feedback, event.aggregate_id)
            if not feedback:
                raise LookupError("feedback no longer exists")
            requirement = await self._feedback_requirement(db, feedback)
            if not requirement.project_id:
                raise LookupError("feedback project is unavailable")
            return IndexableArtifact(
                vector_id=feedback.vector_id or f"feedback:{feedback.id}",
                entity_type="feedback",
                entity_id=str(feedback.id),
                project_id=str(requirement.project_id),
                text=feedback.comment,
                metadata={
                    "target_level": feedback.target_level,
                    "target_id": str(feedback.target_id),
                    "feedback_type": feedback.feedback_type,
                    "status": feedback.status,
                },
            )

        raise ValueError("unsupported outbox event type")

    async def _load_repository_delivery(
        self,
        db: AsyncSession,
        event: OutboxEvent,
    ) -> tuple[RepositoryTestCase, str, str, str]:
        sync_run_id = event.payload.get("sync_run_id")
        if not sync_run_id:
            raise ValueError("repository event is missing sync_run_id")
        sync_run = await db.get(RepositorySyncRun, uuid.UUID(sync_run_id))
        if not sync_run:
            raise LookupError("repository sync run no longer exists")
        result = await db.execute(
            select(TestCase)
            .where(TestCase.id == event.aggregate_id)
            .options(selectinload(TestCase.steps))
        )
        test_case = result.scalars().first()
        if not test_case or test_case.status != "approved":
            raise LookupError("approved test case no longer exists")
        delivery = RepositoryTestCase(
            id=str(test_case.id),
            version=test_case.version,
            requirement_id=str(test_case.requirement_id),
            scenario_id=str(test_case.scenario_id),
            title=test_case.title,
            description=test_case.description,
            prerequisite=test_case.prerequisite,
            priority=test_case.priority,
            severity=test_case.severity,
            category=test_case.category,
            test_type=test_case.type,
            steps=[
                {
                    "step_number": step.step_number,
                    "action": step.action,
                    "expected_result": step.expected_result,
                }
                for step in sorted(test_case.steps, key=lambda item: item.step_number)
            ],
        )
        idempotency_key = event.payload.get("delivery_key") or event.event_key
        return delivery, sync_run.repository, sync_run.branch, idempotency_key

    async def _complete_repository_delivery(self, db: AsyncSession, event: OutboxEvent) -> None:
        test_case = await db.get(TestCase, event.aggregate_id)
        if test_case:
            test_case.repository_status = "synced"
            test_case.repository_synced_at = event.processed_at
        sync_run_id = event.payload.get("sync_run_id")
        if not sync_run_id:
            return
        sync_run = await db.get(RepositorySyncRun, uuid.UUID(sync_run_id), with_for_update=True)
        if not sync_run:
            return
        sync_run.synced_count += 1
        expected_count = int((sync_run.details or {}).get("queued_count", 0))
        if sync_run.synced_count >= expected_count:
            sync_run.status = "completed"
            sync_run.completed_at = event.processed_at

    async def _load_execution(
        self,
        db: AsyncSession,
        event: OutboxEvent,
    ) -> tuple[ExecutableTestCase, str, str]:
        execution_run = await db.get(TestExecutionRun, event.aggregate_id)
        if not execution_run or execution_run.status not in {"queued", "running"}:
            raise LookupError("queued execution run no longer exists")
        result = await db.execute(
            select(TestCase)
            .where(TestCase.id == execution_run.test_case_id)
            .options(selectinload(TestCase.steps))
        )
        test_case = result.scalars().first()
        if not test_case or test_case.status != "approved" or test_case.version != execution_run.test_case_version:
            raise LookupError("approved test case version is no longer executable")
        execution_run.status = "running"
        execution_run.started_at = execution_run.started_at or _utcnow()
        await db.commit()
        return (
            ExecutableTestCase(
                id=str(test_case.id),
                version=test_case.version,
                title=test_case.title,
                description=test_case.description,
                prerequisite=test_case.prerequisite,
                steps=[
                    {
                        "step_number": step.step_number,
                        "action": step.action,
                        "expected_result": step.expected_result,
                    }
                    for step in sorted(test_case.steps, key=lambda item: item.step_number)
                ],
            ),
            execution_run.environment,
            execution_run.idempotency_key,
        )

    async def _complete_execution(
        self,
        db: AsyncSession,
        event: OutboxEvent,
        result: ExecutionResult,
    ) -> None:
        execution_run = await db.get(TestExecutionRun, event.aggregate_id, with_for_update=True)
        if not execution_run:
            return
        execution_run.status = result.status
        execution_run.external_run_id = result.external_run_id
        execution_run.result = result.summary
        execution_run.completed_at = event.processed_at

    async def _feedback_requirement(self, db: AsyncSession, feedback: Feedback) -> Requirement:
        if feedback.target_level == "requirement":
            requirement = await db.get(Requirement, feedback.target_id)
        elif feedback.target_level == "scenario":
            scenario = await db.get(TestScenario, feedback.target_id)
            requirement = await db.get(Requirement, scenario.requirement_id) if scenario else None
        elif feedback.target_level == "test_case":
            test_case = await db.get(TestCase, feedback.target_id)
            requirement = await db.get(Requirement, test_case.requirement_id) if test_case else None
        else:
            requirement = None
        if not requirement:
            raise LookupError("feedback target no longer exists")
        return requirement
