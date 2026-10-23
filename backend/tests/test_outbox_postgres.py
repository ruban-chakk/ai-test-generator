import asyncio
import os
import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.models import (
    Alert,
    OutboxEvent,
    Project,
    RepositorySyncRun,
    Requirement,
    RequirementVersion,
    TestCase as CaseModel,
    TestCaseStep as StepModel,
    TestCaseVersion as VersionModel,
    TestExecutionRun as ExecutionRunModel,
    TestScenario as ScenarioModel,
)
from app.services.indexing import IndexableArtifact
from app.services.execution import ExecutableTestCase, ExecutionResult
from app.services.integrations import RepositoryTestCase
from app.services.outbox import (
    OutboxProcessor,
    REQUIREMENT_VERSION_INDEX_REQUESTED,
    TEST_CASE_INDEX_REQUESTED,
    TEST_CASE_VERSION_INDEX_REQUESTED,
    TEST_CASE_REPOSITORY_SYNC_REQUESTED,
    TEST_CASE_EXECUTION_REQUESTED,
)


TEST_DSN = os.getenv("TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not TEST_DSN, reason="TEST_POSTGRES_DSN is not configured")


class RecordingIndexer:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.artifacts: list[IndexableArtifact] = []

    async def index(self, artifact: IndexableArtifact) -> None:
        self.artifacts.append(artifact)
        if self.fail:
            raise RuntimeError("synthetic provider failure")


class RecordingRepository:
    def __init__(self) -> None:
        self.deliveries: list[tuple[RepositoryTestCase, str, str, str]] = []

    async def upsert(
        self,
        test_case: RepositoryTestCase,
        *,
        repository: str,
        branch: str,
        idempotency_key: str,
    ) -> dict:
        self.deliveries.append((test_case, repository, branch, idempotency_key))
        return {"external_id": test_case.id}


class RecordingExecutionClient:
    def __init__(self, status: str = "passed") -> None:
        self.status = status
        self.executions: list[tuple[ExecutableTestCase, str, str]] = []

    async def execute(
        self,
        test_case: ExecutableTestCase,
        *,
        environment: str,
        idempotency_key: str,
    ) -> ExecutionResult:
        self.executions.append((test_case, environment, idempotency_key))
        return ExecutionResult(
            status=self.status,
            external_run_id="external-run-1",
            summary={"steps_passed": len(test_case.steps)},
        )


async def seed_event(session_factory: async_sessionmaker) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    async with session_factory() as db:
        project = Project(name=f"outbox-test-{uuid.uuid4()}", status="active")
        db.add(project)
        await db.flush()
        requirement = Requirement(
            project_id=project.id,
            title="Password reset",
            description="Users must reset a forgotten password with a time-limited link.",
            source="manual",
            status="generated",
        )
        db.add(requirement)
        await db.flush()
        scenario = ScenarioModel(
            requirement_id=requirement.id,
            title="Expired reset link",
            description="Validate that an expired reset link cannot change credentials.",
            status="approved",
        )
        db.add(scenario)
        await db.flush()
        test_case = CaseModel(
            scenario_id=scenario.id,
            requirement_id=requirement.id,
            title="Reject an expired password reset link",
            description="An expired link is rejected without changing the password.",
            status="approved",
            version=1,
            repository_status="pending_index",
            vector_id=f"test_case:{uuid.uuid4()}:v1",
        )
        db.add(test_case)
        await db.flush()
        db.add(
            StepModel(
                test_case_id=test_case.id,
                step_number=1,
                action="Open the expired password reset link.",
                expected_result="The system rejects the expired link.",
            )
        )
        event = OutboxEvent(
            event_key=f"test_case.index:{test_case.id}:v1",
            event_type=TEST_CASE_INDEX_REQUESTED,
            aggregate_type="test_case",
            aggregate_id=test_case.id,
            payload={"schema_version": 1},
        )
        db.add(event)
        await db.commit()
        return project.id, test_case.id, event.id


async def cleanup(session_factory: async_sessionmaker, project_id: uuid.UUID, event_id: uuid.UUID) -> None:
    async with session_factory() as db:
        requirement_ids = select(Requirement.id).where(Requirement.project_id == project_id)
        case_ids = select(CaseModel.id).where(CaseModel.requirement_id.in_(requirement_ids))
        scenario_ids = select(ScenarioModel.id).where(ScenarioModel.requirement_id.in_(requirement_ids))
        await db.execute(delete(OutboxEvent).where(OutboxEvent.id == event_id))
        await db.execute(delete(StepModel).where(StepModel.test_case_id.in_(case_ids)))
        await db.execute(delete(CaseModel).where(CaseModel.id.in_(case_ids)))
        await db.execute(delete(ScenarioModel).where(ScenarioModel.id.in_(scenario_ids)))
        await db.execute(delete(Requirement).where(Requirement.id.in_(requirement_ids)))
        await db.execute(delete(Project).where(Project.id == project_id))
        await db.commit()


def processor_settings() -> Settings:
    return Settings(
        _env_file=None,
        outbox_batch_size=1,
        outbox_max_attempts=3,
        outbox_lock_timeout_seconds=1,
    )


def test_outbox_worker_indexes_and_completes_event() -> None:
    async def scenario() -> None:
        engine = create_async_engine(TEST_DSN)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        project_id, test_case_id, event_id = await seed_event(session_factory)
        indexer = RecordingIndexer()
        try:
            processor = OutboxProcessor(session_factory, indexer, processor_settings(), worker_id="test-worker")
            assert await processor.process_batch() == 1
            async with session_factory() as db:
                event = await db.get(OutboxEvent, event_id)
                test_case = await db.get(CaseModel, test_case_id)
                assert event.status == "completed"
                assert event.attempts == 1
                # Search projection indexing is independent of approval-version
                # repository delivery state.
                assert test_case.repository_status == "pending_index"
            assert len(indexer.artifacts) == 1
            assert indexer.artifacts[0].project_id == str(project_id)
            assert "expired password reset link" in indexer.artifacts[0].text.lower()
            assert await processor.process_batch() == 0
        finally:
            await cleanup(session_factory, project_id, event_id)
            await engine.dispose()

    asyncio.run(scenario())


def test_outbox_worker_indexes_immutable_requirement_version_snapshot() -> None:
    async def scenario() -> None:
        engine = create_async_engine(TEST_DSN)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        project_id: uuid.UUID | None = None
        requirement_id: uuid.UUID | None = None
        event_id: uuid.UUID | None = None
        indexer = RecordingIndexer()
        try:
            async with session_factory() as db:
                project = Project(name=f"requirement-version-{uuid.uuid4()}", status="active")
                db.add(project)
                await db.flush()
                project_id = project.id
                requirement = Requirement(
                    project_id=project.id,
                    external_id="REQ-VERSION-1",
                    title="A later canonical requirement title",
                    description="The mutable row has changed after the approved historical snapshot.",
                    source="jira",
                    status="draft",
                    version=2,
                )
                db.add(requirement)
                await db.flush()
                requirement_id = requirement.id
                version = RequirementVersion(
                    requirement_id=requirement.id,
                    project_id=project.id,
                    version=1,
                    external_id="REQ-VERSION-1",
                    title="Immutable historical requirement title",
                    description="The historical requirement must be indexed from this snapshot.",
                    source="jira",
                    status="approved",
                    vector_id=f"requirement:{requirement.id}:v1",
                )
                db.add(version)
                await db.flush()
                event = OutboxEvent(
                    event_key=f"requirement_version.index:{version.id}",
                    event_type=REQUIREMENT_VERSION_INDEX_REQUESTED,
                    aggregate_type="requirement_version",
                    aggregate_id=version.id,
                    payload={
                        "schema_version": 1,
                        "requirement_id": str(requirement.id),
                        "version": 1,
                    },
                )
                db.add(event)
                await db.commit()
                event_id = event.id

            processor = OutboxProcessor(
                session_factory,
                indexer,
                processor_settings(),
                worker_id="requirement-version-index-worker",
            )
            assert await processor.process_batch() == 1
            assert len(indexer.artifacts) == 1
            artifact = indexer.artifacts[0]
            assert artifact.vector_id == f"requirement:{requirement_id}:v1"
            assert "Immutable historical requirement title" in artifact.text
            assert "later canonical" not in artifact.text
            assert artifact.metadata["immutable_version"] is True
            async with session_factory() as db:
                event = await db.get(OutboxEvent, event_id)
                assert event.status == "completed"
        finally:
            if event_id is not None:
                async with session_factory() as db:
                    await db.execute(delete(OutboxEvent).where(OutboxEvent.id == event_id))
                    if requirement_id is not None:
                        await db.execute(delete(Requirement).where(Requirement.id == requirement_id))
                    if project_id is not None:
                        await db.execute(delete(Project).where(Project.id == project_id))
                    await db.commit()
            await engine.dispose()

    asyncio.run(scenario())


def test_outbox_worker_indexes_immutable_test_case_version_snapshot() -> None:
    async def scenario() -> None:
        engine = create_async_engine(TEST_DSN)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        project_id, test_case_id, event_id = await seed_event(session_factory)
        indexer = RecordingIndexer()
        try:
            async with session_factory() as db:
                test_case = await db.get(CaseModel, test_case_id)
                version = VersionModel(
                    test_case_id=test_case.id,
                    requirement_id=test_case.requirement_id,
                    scenario_id=test_case.scenario_id,
                    version=1,
                    source="generated",
                    title="Immutable approved reset-link behavior",
                    description="The approved snapshot rejects an expired reset link.",
                    priority="high",
                    severity="major",
                    status="approved",
                    approved_by="approver",
                    steps_snapshot=[
                        {
                            "step_number": 1,
                            "action": "Open the expired reset link.",
                            "expected_result": "The approved snapshot rejects the link.",
                        }
                    ],
                    vector_id=f"test_case:{test_case.id}:v1",
                )
                db.add(version)
                await db.flush()
                event = await db.get(OutboxEvent, event_id)
                event.event_type = TEST_CASE_VERSION_INDEX_REQUESTED
                event.event_key = f"test_case_version.index:{version.id}"
                event.aggregate_type = "test_case_version"
                event.aggregate_id = version.id
                event.payload = {
                    "schema_version": 1,
                    "test_case_id": str(test_case.id),
                    "version": 1,
                }
                test_case.title = "A later canonical mutation must not alter the snapshot"
                await db.commit()

            processor = OutboxProcessor(
                session_factory,
                indexer,
                processor_settings(),
                worker_id="version-index-worker",
            )
            assert await processor.process_batch() == 1
            assert len(indexer.artifacts) == 1
            artifact = indexer.artifacts[0]
            assert artifact.vector_id == f"test_case:{test_case_id}:v1"
            assert "Immutable approved reset-link behavior" in artifact.text
            assert "later canonical mutation" not in artifact.text
            assert artifact.metadata["immutable_version"] is True
            async with session_factory() as db:
                test_case = await db.get(CaseModel, test_case_id)
                assert test_case.repository_status == "indexed"
                assert test_case.vector_id == artifact.vector_id
        finally:
            await cleanup(session_factory, project_id, event_id)
            await engine.dispose()

    asyncio.run(scenario())


def test_failed_execution_creates_one_durable_project_alert() -> None:
    async def scenario() -> None:
        engine = create_async_engine(TEST_DSN)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        project_id, test_case_id, event_id = await seed_event(session_factory)
        async with session_factory() as db:
            execution_run = ExecutionRunModel(
                project_id=project_id,
                test_case_id=test_case_id,
                test_case_version=1,
                environment="production",
                runner="generic",
                status="queued",
                idempotency_key=f"execution-failure-{uuid.uuid4()}",
                result={},
                requested_by="integration-test",
            )
            db.add(execution_run)
            await db.flush()
            execution_run_id = execution_run.id
            event = await db.get(OutboxEvent, event_id)
            event.event_type = TEST_CASE_EXECUTION_REQUESTED
            event.event_key = f"execution.run:{execution_run.id}"
            event.aggregate_type = "test_execution_run"
            event.aggregate_id = execution_run.id
            await db.commit()

        try:
            processor = OutboxProcessor(
                session_factory,
                config=processor_settings(),
                worker_id="failed-execution-worker",
                execution_client=RecordingExecutionClient(status="failed"),  # type: ignore[arg-type]
            )
            assert await processor.process_batch() == 1
            async with session_factory() as db:
                alerts = (
                    await db.execute(select(Alert).where(Alert.project_id == project_id))
                ).scalars().all()
                assert len(alerts) == 1
                assert alerts[0].category == "test_execution_failed"
                assert alerts[0].delivery_status == "not_configured"
                assert alerts[0].details["execution_run_id"] == str(execution_run_id)
        finally:
            await cleanup(session_factory, project_id, event_id)
            await engine.dispose()

    asyncio.run(scenario())


def test_outbox_worker_retries_without_storing_provider_message() -> None:
    async def scenario() -> None:
        engine = create_async_engine(TEST_DSN)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        project_id, _, event_id = await seed_event(session_factory)
        try:
            processor = OutboxProcessor(
                session_factory,
                RecordingIndexer(fail=True),
                processor_settings(),
                worker_id="failing-test-worker",
            )
            assert await processor.process_batch() == 1
            async with session_factory() as db:
                event = await db.get(OutboxEvent, event_id)
                assert event.status == "pending"
                assert event.attempts == 1
                assert event.last_error == "RuntimeError"
                assert "synthetic" not in event.last_error
        finally:
            await cleanup(session_factory, project_id, event_id)
            await engine.dispose()

    asyncio.run(scenario())


def test_outbox_worker_delivers_repository_case_and_completes_run() -> None:
    async def scenario() -> None:
        engine = create_async_engine(TEST_DSN)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        project_id, test_case_id, event_id = await seed_event(session_factory)
        async with session_factory() as db:
            sync_run = RepositorySyncRun(
                repository="qa-cases",
                branch="main",
                status="queued",
                requested_by="integration-test",
                details={"queued_count": 1, "project_id": str(project_id)},
            )
            db.add(sync_run)
            await db.flush()
            sync_run_id = sync_run.id
            event = await db.get(OutboxEvent, event_id)
            event.event_type = TEST_CASE_REPOSITORY_SYNC_REQUESTED
            event.event_key = f"repository.delivery:{sync_run.id}:{test_case_id}"
            event.payload = {
                "schema_version": 1,
                "sync_run_id": str(sync_run.id),
                "delivery_key": "stable-delivery-key",
            }
            test_case = await db.get(CaseModel, test_case_id)
            test_case.repository_status = "pending_sync"
            await db.commit()

        repository = RecordingRepository()
        try:
            processor = OutboxProcessor(
                session_factory,
                config=processor_settings(),
                worker_id="repository-test-worker",
                repository_client=repository,  # type: ignore[arg-type]
            )
            assert await processor.process_batch() == 1
            async with session_factory() as db:
                event = await db.get(OutboxEvent, event_id)
                test_case = await db.get(CaseModel, test_case_id)
                sync_run = await db.get(RepositorySyncRun, sync_run_id)
                assert event.status == "completed"
                assert test_case.repository_status == "synced"
                assert sync_run.status == "completed"
                assert sync_run.synced_count == 1
            assert len(repository.deliveries) == 1
            delivered, repository_name, branch, key = repository.deliveries[0]
            assert delivered.id == str(test_case_id)
            assert repository_name == "qa-cases"
            assert branch == "main"
            assert key == "stable-delivery-key"
        finally:
            async with session_factory() as db:
                await db.execute(delete(RepositorySyncRun).where(RepositorySyncRun.id == sync_run_id))
                await db.commit()
            await cleanup(session_factory, project_id, event_id)
            await engine.dispose()

    asyncio.run(scenario())


def test_outbox_worker_executes_approved_case_and_records_terminal_result() -> None:
    async def scenario() -> None:
        engine = create_async_engine(TEST_DSN)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        project_id, test_case_id, event_id = await seed_event(session_factory)
        async with session_factory() as db:
            execution_run = ExecutionRunModel(
                project_id=project_id,
                test_case_id=test_case_id,
                test_case_version=1,
                environment="staging",
                runner="generic",
                status="queued",
                idempotency_key="execution-stable-key",
                result={},
                requested_by="integration-test",
            )
            db.add(execution_run)
            await db.flush()
            execution_run_id = execution_run.id
            event = await db.get(OutboxEvent, event_id)
            event.event_type = TEST_CASE_EXECUTION_REQUESTED
            event.event_key = f"execution.run:{execution_run.id}"
            event.aggregate_type = "test_execution_run"
            event.aggregate_id = execution_run.id
            await db.commit()

        runner = RecordingExecutionClient()
        try:
            processor = OutboxProcessor(
                session_factory,
                config=processor_settings(),
                worker_id="execution-test-worker",
                execution_client=runner,  # type: ignore[arg-type]
            )
            assert await processor.process_batch() == 1
            async with session_factory() as db:
                event = await db.get(OutboxEvent, event_id)
                execution_run = await db.get(ExecutionRunModel, execution_run_id)
                assert event.status == "completed"
                assert execution_run.status == "passed"
                assert execution_run.external_run_id == "external-run-1"
                assert execution_run.result == {"steps_passed": 1}
                assert execution_run.started_at is not None
                assert execution_run.completed_at is not None
            assert len(runner.executions) == 1
            delivered, environment, key = runner.executions[0]
            assert delivered.id == str(test_case_id)
            assert environment == "staging"
            assert key == "execution-stable-key"
        finally:
            await cleanup(session_factory, project_id, event_id)
            await engine.dispose()

    asyncio.run(scenario())
