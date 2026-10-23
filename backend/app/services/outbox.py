from __future__ import annotations

import uuid
import json
import logging
import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.core.config import Settings, settings
from app.models import (
    Alert,
    Feedback,
    KnowledgeDocument,
    OutboxEvent,
    QualityEvaluation,
    RepositorySyncRun,
    Requirement,
    RequirementVersion,
    TestCase,
    TestCaseVersion,
    TestExecutionRun,
    TestScenario,
    VectorChunk,
)
from app.services.alerts import ALERT_DELIVERY_REQUESTED, AlertWebhookClient, create_alert
from app.services.execution import ExecutableTestCase, ExecutionResult, TestExecutionClient
from app.services.integrations import RepositoryClient, RepositoryTestCase, build_test_repository_client
from app.services.indexing import IndexableArtifact, IndexingResult, IndexingService, build_indexing_service

logger = logging.getLogger(__name__)


TEST_CASE_INDEX_REQUESTED = "test_case.index_requested"
TEST_CASE_VERSION_INDEX_REQUESTED = "test_case_version.index_requested"
FEEDBACK_INDEX_REQUESTED = "feedback.index_requested"
KNOWLEDGE_DOCUMENT_INDEX_REQUESTED = "knowledge_document.index_requested"
REQUIREMENT_INDEX_REQUESTED = "requirement.index_requested"
REQUIREMENT_VERSION_INDEX_REQUESTED = "requirement_version.index_requested"
TEST_CASE_REPOSITORY_SYNC_REQUESTED = "test_case.repository_sync_requested"
TEST_CASE_EXECUTION_REQUESTED = "test_case.execution_requested"
TEST_CASE_QUALITY_EVALUATION_REQUESTED = "test_case.quality_evaluation_requested"


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _text_with_custom_fields(text: str, custom_fields: dict, schema: dict | None = None) -> str:
    schema = schema or {}
    indexed_fields = {
        key: value
        for key, value in custom_fields.items()
        if not isinstance(schema.get(key), dict)
        or (
            schema[key].get("index", True) is not False
            and int(schema[key].get("semantic_weight", 1)) > 0
        )
    }
    if not indexed_fields:
        return text
    rendered = json.dumps(indexed_fields, ensure_ascii=False, sort_keys=True, default=str)
    return f"{text}\nCustom fields: {rendered[:8000]}"


def _custom_field_segments(custom_fields: dict, schema: dict | None = None) -> tuple[str, ...]:
    segments: list[str] = []
    schema = schema or {}
    for key, value in sorted(custom_fields.items()):
        policy = schema.get(key, {}) if isinstance(schema.get(key, {}), dict) else {}
        if policy.get("index", True) is False or int(policy.get("semantic_weight", 1)) == 0:
            continue
        segment = f"Custom field {key}: {json.dumps(value, ensure_ascii=False, default=str)}"
        segments.extend([segment] * min(3, max(1, int(policy.get("semantic_weight", 1)))))
    return tuple(segments)


def _custom_field_metadata(custom_fields: dict, schema: dict | None = None) -> dict:
    metadata: dict = {}
    schema = schema or {}
    for key, value in custom_fields.items():
        policy = schema.get(key, {}) if isinstance(schema.get(key, {}), dict) else {}
        if policy.get("index", True) is False:
            continue
        safe_key = re.sub(r"[^a-z0-9]+", "_", str(key).lower()).strip("_")[:80]
        if not safe_key:
            continue
        if isinstance(value, (str, int, float, bool)):
            metadata[f"custom__{safe_key}"] = value
        elif isinstance(value, list) and all(isinstance(item, (str, int, float, bool)) for item in value):
            metadata[f"custom__{safe_key}"] = value[:100]
        else:
            metadata[f"custom__{safe_key}"] = json.dumps(value, ensure_ascii=False, default=str)[:1000]
    return metadata


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
    payload: dict | None = None,
) -> OutboxEvent:
    return enqueue_outbox_event(
        db,
        event_key=event_key,
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload=payload,
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
        alert_client: AlertWebhookClient | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._indexing_service = indexing_service
        self._repository_client = repository_client
        self._execution_client = execution_client
        self._alert_client = alert_client
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
        indexing_result: IndexingResult | None = None
        indexed_artifact: IndexableArtifact | None = None
        try:
            async with self._session_factory() as db:
                event = await db.get(OutboxEvent, event_id)
                if not event or event.status != "processing" or event.locked_by != self._worker_id:
                    return
                if event.event_type in {
                    REQUIREMENT_INDEX_REQUESTED,
                    REQUIREMENT_VERSION_INDEX_REQUESTED,
                    TEST_CASE_INDEX_REQUESTED,
                    TEST_CASE_VERSION_INDEX_REQUESTED,
                    FEEDBACK_INDEX_REQUESTED,
                    KNOWLEDGE_DOCUMENT_INDEX_REQUESTED,
                }:
                    operation = ("index", await self._load_artifact(db, event))
                elif event.event_type == TEST_CASE_REPOSITORY_SYNC_REQUESTED:
                    operation = ("repository", await self._load_repository_delivery(db, event))
                elif event.event_type == TEST_CASE_EXECUTION_REQUESTED:
                    operation = ("execution", await self._load_execution(db, event))
                elif event.event_type == TEST_CASE_QUALITY_EVALUATION_REQUESTED:
                    existing = await db.scalar(
                        select(QualityEvaluation).where(QualityEvaluation.source_event_id == event.id)
                    )
                    operation = (
                        "noop",
                        None,
                    ) if existing else (
                        "quality",
                        (event.id, event.aggregate_id, dict(event.payload or {})),
                    )
                elif event.event_type == ALERT_DELIVERY_REQUESTED:
                    operation = ("alert", await self._load_alert(db, event))
                else:
                    raise ValueError("unsupported outbox event type")
            if operation[0] == "index":
                if self._indexing_service is None:
                    self._indexing_service = build_indexing_service(self._config)
                indexed_artifact = operation[1]
                indexing_result = await self._indexing_service.index(indexed_artifact)
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
            elif operation[0] == "execution":
                if self._execution_client is None:
                    self._execution_client = TestExecutionClient(self._config)
                test_case, environment, idempotency_key = operation[1]
                execution_result = await self._execution_client.execute(
                    test_case,
                    environment=environment,
                    idempotency_key=idempotency_key,
                )
            elif operation[0] == "quality":
                source_event_id, test_case_id, payload = operation[1]
                await self._evaluate_test_case(source_event_id, test_case_id, payload)
            elif operation[0] == "alert":
                if self._alert_client is None:
                    self._alert_client = AlertWebhookClient(self._config)
                alert, idempotency_key = operation[1]
                await self._alert_client.deliver(alert, idempotency_key=idempotency_key)
        except Exception as exc:
            logger.exception("Outbox event %s failed", event_id)
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
            if indexing_result is not None and indexed_artifact is not None:
                await self._replace_vector_chunk_inventory(db, event, indexed_artifact, indexing_result)
            if event.event_type == REQUIREMENT_INDEX_REQUESTED:
                requirement = await db.get(Requirement, event.aggregate_id)
                if requirement:
                    requirement.vector_id = requirement.vector_id or f"requirement:{requirement.id}"
            elif event.event_type == REQUIREMENT_VERSION_INDEX_REQUESTED:
                version = await db.get(RequirementVersion, event.aggregate_id)
                if version:
                    version.vector_id = version.vector_id or f"requirement:{version.requirement_id}:v{version.version}"
                    requirement = await db.get(Requirement, version.requirement_id)
                    if requirement and requirement.version == version.version:
                        requirement.vector_id = version.vector_id
            elif event.event_type == TEST_CASE_INDEX_REQUESTED:
                # Current-record vectors power Search for every workflow state.
                # Repository delivery status is governed by approved-version indexing
                # and repository sync, not by this search projection.
                pass
            elif event.event_type == TEST_CASE_VERSION_INDEX_REQUESTED:
                version = await db.get(TestCaseVersion, event.aggregate_id)
                if version:
                    version.vector_id = version.vector_id or f"test_case:{version.test_case_id}:v{version.version}"
                    test_case = await db.get(TestCase, version.test_case_id)
                    if test_case and test_case.version == version.version:
                        test_case.vector_id = version.vector_id
                        test_case.repository_status = "indexed"
                        test_case.repository_synced_at = event.processed_at
            elif event.event_type == KNOWLEDGE_DOCUMENT_INDEX_REQUESTED:
                document = await db.get(KnowledgeDocument, event.aggregate_id)
                if document:
                    document.vector_id = document.vector_id or f"knowledge_document:{document.id}"
                    document.status = "indexed"
            elif event.event_type == TEST_CASE_REPOSITORY_SYNC_REQUESTED:
                await self._complete_repository_delivery(db, event)
            elif event.event_type == TEST_CASE_EXECUTION_REQUESTED and execution_result is not None:
                await self._complete_execution(db, event, execution_result)
            elif event.event_type == ALERT_DELIVERY_REQUESTED:
                await self._complete_alert_delivery(db, event)
            await db.commit()

    async def _evaluate_test_case(
        self,
        source_event_id: uuid.UUID,
        test_case_id: uuid.UUID,
        payload: dict,
    ) -> None:
        # Imported lazily to keep HTTP adapters out of the outbox module's import
        # graph while reusing the same authoritative evaluation transaction.
        from app.api.routes import _evaluate_quality_impl
        from app.core.security import Principal, _principal_context

        try:
            actor_id = uuid.UUID(str(payload["requested_by_id"]))
            actor = str(payload["requested_by"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("quality evaluation event has no valid actor") from exc

        principal_token = _principal_context.set(
            Principal(
                user_id=actor_id,
                username=actor,
                role="app_admin",
                token_version=0,
            )
        )
        try:
            async with self._session_factory() as db:
                await _evaluate_quality_impl(
                    "test_case",
                    str(test_case_id),
                    db,
                    source_event_id=source_event_id,
                )
        finally:
            _principal_context.reset(principal_token)

    async def _replace_vector_chunk_inventory(
        self,
        db: AsyncSession,
        event: OutboxEvent,
        artifact: IndexableArtifact,
        result: IndexingResult,
    ) -> None:
        await db.execute(
            delete(VectorChunk).where(
                VectorChunk.aggregate_type == event.aggregate_type,
                VectorChunk.aggregate_id == event.aggregate_id,
            )
        )
        now = _utcnow()
        for chunk in result.chunks:
            db.add(
                VectorChunk(
                    project_id=uuid.UUID(artifact.project_id),
                    aggregate_type=event.aggregate_type,
                    aggregate_id=event.aggregate_id,
                    entity_type=artifact.entity_type,
                    entity_id=uuid.UUID(artifact.entity_id),
                    vector_id=chunk.vector_id,
                    chunk_index=chunk.chunk_index,
                    chunk_count=chunk.chunk_count,
                    content_sha256=chunk.content_sha256,
                    indexed_at=now,
                )
            )

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
            if exhausted and event.event_type == ALERT_DELIVERY_REQUESTED:
                alert = await db.get(Alert, event.aggregate_id)
                if alert:
                    alert.delivery_status = "failed"
            elif exhausted:
                project_id = await self._event_project_id(db, event)
                await create_alert(
                    db,
                    dedupe_key=f"outbox-exhausted:{event.id}",
                    category="outbox_exhausted",
                    severity="critical",
                    title=f"Delivery exhausted for {event.event_type}",
                    details={
                        "event_id": str(event.id),
                        "event_type": event.event_type,
                        "aggregate_type": event.aggregate_type,
                        "aggregate_id": str(event.aggregate_id),
                        "attempts": event.attempts,
                        "failure_type": error_type[:255],
                    },
                    project_id=project_id,
                    config=self._config,
                )
            await db.commit()

    async def _load_artifact(self, db: AsyncSession, event: OutboxEvent) -> IndexableArtifact:
        if event.event_type == REQUIREMENT_INDEX_REQUESTED:
            requirement = await db.get(Requirement, event.aggregate_id)
            if not requirement or not requirement.project_id:
                raise LookupError("requirement project is unavailable")
            custom_fields = (requirement.metadata_json or {}).get("custom_fields", {})
            custom_schema = (requirement.metadata_json or {}).get("custom_field_schema", {})
            return await self._tracked_artifact(db, event, IndexableArtifact(
                vector_id=requirement.vector_id or f"requirement:{requirement.id}",
                entity_type="requirement",
                entity_id=str(requirement.id),
                project_id=str(requirement.project_id),
                text=_text_with_custom_fields(
                    f"Title: {requirement.title}\nDescription: {requirement.description}",
                    custom_fields,
                    custom_schema,
                ),
                logical_segments=(
                    f"Requirement: {requirement.external_id or requirement.id} — {requirement.title}",
                    f"Description: {requirement.description}",
                    *_custom_field_segments(custom_fields, custom_schema),
                ),
                metadata={
                    "requirement_id": str(requirement.id),
                    "external_id": requirement.external_id or "",
                    "source": requirement.source,
                    "status": requirement.status,
                    **_custom_field_metadata(custom_fields, custom_schema),
                },
            ))

        if event.event_type == REQUIREMENT_VERSION_INDEX_REQUESTED:
            version = await db.get(RequirementVersion, event.aggregate_id)
            if not version or not version.project_id:
                raise LookupError("requirement version project is unavailable")
            custom_fields = (version.metadata_json or {}).get("custom_fields", {})
            custom_schema = (version.metadata_json or {}).get("custom_field_schema", {})
            return await self._tracked_artifact(db, event, IndexableArtifact(
                vector_id=version.vector_id or f"requirement:{version.requirement_id}:v{version.version}",
                entity_type="requirement",
                entity_id=str(version.requirement_id),
                project_id=str(version.project_id),
                text=_text_with_custom_fields(
                    f"Title: {version.title}\nDescription: {version.description}",
                    custom_fields,
                    custom_schema,
                ),
                logical_segments=(
                    f"Requirement: {version.external_id or version.requirement_id} — {version.title}",
                    f"Description: {version.description}",
                    *_custom_field_segments(custom_fields, custom_schema),
                ),
                metadata={
                    "requirement_version_id": str(version.id),
                    "requirement_id": str(version.requirement_id),
                    "external_id": version.external_id or "",
                    "source": version.source,
                    "status": version.status,
                    "title": version.title,
                    "version": version.version,
                    "created_at": version.created_at.isoformat(),
                    "immutable_version": True,
                    **_custom_field_metadata(custom_fields, custom_schema),
                },
            ))

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
            text = _text_with_custom_fields(
                text,
                test_case.custom_fields_json or {},
                test_case.custom_field_schema_json or {},
            )
            identity = f"Test case: {test_case.external_id or test_case.id} — {test_case.title}"
            return await self._tracked_artifact(db, event, IndexableArtifact(
                vector_id=f"test_case:{test_case.id}:current",
                entity_type="test_case",
                entity_id=str(test_case.id),
                project_id=str(requirement.project_id),
                text=text,
                logical_segments=(
                    identity,
                    f"Description: {test_case.description}",
                    *((f"Prerequisite: {test_case.prerequisite}",) if test_case.prerequisite else ()),
                    *tuple(
                        f"Step {step.step_number}: {step.action}\nExpected: {step.expected_result}"
                        for step in sorted(test_case.steps, key=lambda item: item.step_number)
                    ),
                    *_custom_field_segments(
                        test_case.custom_fields_json or {}, test_case.custom_field_schema_json or {}
                    ),
                ),
                metadata={
                    "requirement_id": str(test_case.requirement_id),
                    "scenario_id": str(test_case.scenario_id),
                    "title": test_case.title,
                    "status": test_case.status,
                    "repository_status": test_case.repository_status,
                    "version": test_case.version,
                    "artifact_scope": "current",
                    "priority": test_case.priority or "",
                    "severity": test_case.severity or "",
                    "category": test_case.category or "",
                    "type": test_case.type or "",
                    **_custom_field_metadata(
                        test_case.custom_fields_json or {}, test_case.custom_field_schema_json or {}
                    ),
                },
            ))

        if event.event_type == TEST_CASE_VERSION_INDEX_REQUESTED:
            version = await db.get(TestCaseVersion, event.aggregate_id)
            if not version:
                raise LookupError("test case version no longer exists")
            requirement = await db.get(Requirement, version.requirement_id)
            if not requirement or not requirement.project_id:
                raise LookupError("test case version project is unavailable")
            step_text = " ".join(
                f"Step {step.get('step_number')}: {step.get('action', '')} "
                f"Expected: {step.get('expected_result', '')}"
                for step in sorted(
                    version.steps_snapshot or [],
                    key=lambda item: int(item.get("step_number", 0)),
                )
            )
            text = " ".join(
                part
                for part in [
                    version.title,
                    version.description,
                    version.prerequisite,
                    step_text,
                ]
                if part
            )
            text = _text_with_custom_fields(
                text,
                version.custom_fields_json or {},
                version.custom_field_schema_json or {},
            )
            identity = f"Test case: {version.external_id or version.test_case_id} — {version.title}"
            return await self._tracked_artifact(db, event, IndexableArtifact(
                vector_id=version.vector_id or f"test_case:{version.test_case_id}:v{version.version}",
                entity_type="test_case",
                entity_id=str(version.test_case_id),
                project_id=str(requirement.project_id),
                text=text,
                logical_segments=(
                    identity,
                    f"Description: {version.description}",
                    *((f"Prerequisite: {version.prerequisite}",) if version.prerequisite else ()),
                    *tuple(
                        f"Step {step.get('step_number')}: {step.get('action', '')}\n"
                        f"Expected: {step.get('expected_result', '')}"
                        for step in sorted(
                            version.steps_snapshot or [],
                            key=lambda item: int(item.get("step_number", 0)),
                        )
                    ),
                    *_custom_field_segments(
                        version.custom_fields_json or {}, version.custom_field_schema_json or {}
                    ),
                ),
                metadata={
                    "test_case_version_id": str(version.id),
                    "requirement_id": str(version.requirement_id),
                    "scenario_id": str(version.scenario_id),
                    "external_id": version.external_id or "",
                    "source": version.source,
                    "title": version.title,
                    "status": version.status,
                    "repository_status": "indexed",
                    "version": version.version,
                    "priority": version.priority or "",
                    "severity": version.severity or "",
                    "category": version.category or "",
                    "type": version.type or "",
                    "approved_at": version.approved_at.isoformat(),
                    "immutable_version": True,
                    "artifact_scope": "approved_version",
                    "rag_eligible": True,
                    **_custom_field_metadata(
                        version.custom_fields_json or {}, version.custom_field_schema_json or {}
                    ),
                },
            ))

        if event.event_type == FEEDBACK_INDEX_REQUESTED:
            feedback = await db.get(Feedback, event.aggregate_id)
            if not feedback:
                raise LookupError("feedback no longer exists")
            requirement = await self._feedback_requirement(db, feedback)
            if not requirement.project_id:
                raise LookupError("feedback project is unavailable")
            return await self._tracked_artifact(db, event, IndexableArtifact(
                vector_id=feedback.vector_id or f"feedback:{feedback.id}",
                entity_type="feedback",
                entity_id=str(feedback.id),
                project_id=str(requirement.project_id),
                text=feedback.comment,
                logical_segments=(
                    f"{feedback.feedback_type.replace('_', ' ').title()} feedback",
                    feedback.comment,
                ),
                metadata={
                    "target_level": feedback.target_level,
                    "target_id": str(feedback.target_id),
                    "feedback_type": feedback.feedback_type,
                    "status": feedback.status,
                },
            ))

        if event.event_type == KNOWLEDGE_DOCUMENT_INDEX_REQUESTED:
            document = await db.get(KnowledgeDocument, event.aggregate_id)
            if not document:
                raise LookupError("knowledge document no longer exists")
            return await self._tracked_artifact(db, event, IndexableArtifact(
                vector_id=document.vector_id or f"knowledge_document:{document.id}",
                entity_type="knowledge_document",
                entity_id=str(document.id),
                project_id=str(document.project_id),
                text=f"Title: {document.title}\nContent: {document.content}",
                logical_segments=(
                    f"Supporting document: {document.title}",
                    document.content,
                ),
                metadata={
                    "title": document.title,
                    "source": document.source,
                    "status": document.status,
                },
            ))

        raise ValueError("unsupported outbox event type")

    async def _tracked_artifact(
        self,
        db: AsyncSession,
        event: OutboxEvent,
        artifact: IndexableArtifact,
    ) -> IndexableArtifact:
        existing = tuple(
            (
                await db.execute(
                    select(VectorChunk.vector_id).where(
                        VectorChunk.aggregate_type == event.aggregate_type,
                        VectorChunk.aggregate_id == event.aggregate_id,
                    )
                )
            ).scalars().all()
        )
        return replace(artifact, existing_vector_ids=existing)

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
        if result.status == "failed":
            await create_alert(
                db,
                dedupe_key=f"execution-failed:{execution_run.id}",
                category="test_execution_failed",
                severity="high",
                title="Automated test execution failed",
                details={
                    "execution_run_id": str(execution_run.id),
                    "test_case_id": str(execution_run.test_case_id),
                    "test_case_version": execution_run.test_case_version,
                    "environment": execution_run.environment,
                    "external_run_id": execution_run.external_run_id,
                },
                project_id=execution_run.project_id,
                config=self._config,
            )

    async def _load_alert(self, db: AsyncSession, event: OutboxEvent) -> tuple[Alert, str]:
        alert = await db.get(Alert, event.aggregate_id)
        if not alert or alert.delivery_status not in {"pending", "failed"}:
            raise LookupError("pending alert no longer exists")
        return alert, event.event_key

    async def _complete_alert_delivery(self, db: AsyncSession, event: OutboxEvent) -> None:
        alert = await db.get(Alert, event.aggregate_id, with_for_update=True)
        if alert:
            alert.delivery_status = "delivered"
            alert.delivered_at = event.processed_at

    async def _event_project_id(self, db: AsyncSession, event: OutboxEvent) -> uuid.UUID | None:
        if event.event_type == REQUIREMENT_INDEX_REQUESTED:
            requirement = await db.get(Requirement, event.aggregate_id)
            return requirement.project_id if requirement else None
        if event.event_type == REQUIREMENT_VERSION_INDEX_REQUESTED:
            version = await db.get(RequirementVersion, event.aggregate_id)
            return version.project_id if version else None
        if event.event_type == TEST_CASE_INDEX_REQUESTED:
            test_case = await db.get(TestCase, event.aggregate_id)
            requirement = await db.get(Requirement, test_case.requirement_id) if test_case else None
            return requirement.project_id if requirement else None
        if event.event_type == TEST_CASE_VERSION_INDEX_REQUESTED:
            version = await db.get(TestCaseVersion, event.aggregate_id)
            requirement = await db.get(Requirement, version.requirement_id) if version else None
            return requirement.project_id if requirement else None
        if event.event_type == FEEDBACK_INDEX_REQUESTED:
            feedback = await db.get(Feedback, event.aggregate_id)
            requirement = await self._feedback_requirement(db, feedback) if feedback else None
            return requirement.project_id if requirement else None
        if event.event_type == KNOWLEDGE_DOCUMENT_INDEX_REQUESTED:
            document = await db.get(KnowledgeDocument, event.aggregate_id)
            return document.project_id if document else None
        if event.event_type == TEST_CASE_EXECUTION_REQUESTED:
            execution_run = await db.get(TestExecutionRun, event.aggregate_id)
            return execution_run.project_id if execution_run else None
        if event.event_type == TEST_CASE_QUALITY_EVALUATION_REQUESTED:
            test_case = await db.get(TestCase, event.aggregate_id)
            requirement = await db.get(Requirement, test_case.requirement_id) if test_case else None
            return requirement.project_id if requirement else None
        if event.event_type == TEST_CASE_REPOSITORY_SYNC_REQUESTED:
            sync_run_id = event.payload.get("sync_run_id")
            if sync_run_id:
                try:
                    sync_run = await db.get(RepositorySyncRun, uuid.UUID(sync_run_id))
                except (TypeError, ValueError, AttributeError):
                    sync_run = None
                project_id = (sync_run.details or {}).get("project_id") if sync_run else None
                try:
                    return uuid.UUID(project_id) if project_id else None
                except (TypeError, ValueError, AttributeError):
                    return None
        return None

    async def _feedback_requirement(self, db: AsyncSession, feedback: Feedback) -> Requirement:
        if feedback.target_level in {"requirement", "suite"}:
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
