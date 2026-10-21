import asyncio
import json
import os
import uuid

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.models import (
    ApprovalRecord,
    AuditLog,
    IntegrationRun,
    OutboxEvent,
    Project,
    Requirement,
    TestCase as CaseModel,
    TestCaseStep as StepModel,
    TestCaseVersion as VersionModel,
    TestScenario as ScenarioModel,
)
from app.services.historical_import import (
    HistoricalImportConflictError,
    import_historical_test_cases,
)
from app.services.historical_ingestion import parse_historical_test_case_file
from app.services.outbox import OutboxProcessor, TEST_CASE_VERSION_INDEX_REQUESTED


TEST_DSN = os.getenv("TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not TEST_DSN, reason="TEST_POSTGRES_DSN is not configured")


def payload(requirement_external_id: str) -> bytes:
    return json.dumps(
        {
            "test_cases": [
                {
                    "external_id": "LEGACY-TC-17",
                    "requirement_external_id": requirement_external_id,
                    "scenario_external_id": "LEGACY-SC-4",
                    "scenario_title": "Historical password reset coverage",
                    "scenario_description": "Validate password reset controls imported from the legacy repository.",
                    "title": "Reject a previously consumed password reset link",
                    "description": "A consumed reset link must not change credentials or expose token data.",
                    "prerequisite": "A password reset link has already been used successfully.",
                    "priority": "high",
                    "severity": "major",
                    "category": "security",
                    "type": "regression",
                    "status": "approved",
                    "version": 4,
                    "approved_at": "2024-06-01T10:30:00Z",
                    "approved_by": "legacy-qa-lead",
                    "steps": [
                        {
                            "step_number": 1,
                            "action": "Open the previously consumed password reset link.",
                            "expected_result": "The application rejects the link without changing credentials.",
                        }
                    ],
                }
            ]
        }
    ).encode()


def test_historical_import_is_atomic_idempotent_and_indexes_immutable_version() -> None:
    async def scenario() -> None:
        engine = create_async_engine(TEST_DSN)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        actor = f"historical-import-test-{uuid.uuid4()}"
        project_id: uuid.UUID | None = None
        try:
            requirement_external_id = f"LEGACY-REQ-{uuid.uuid4()}"
            async with session_factory() as db:
                project = Project(name=f"historical-import-{uuid.uuid4()}", status="active")
                db.add(project)
                await db.flush()
                project_id = project.id
                requirement = Requirement(
                    project_id=project.id,
                    external_id=requirement_external_id,
                    title="Secure password reset",
                    description="Users must reset passwords with single-use, time-limited links.",
                    source="upload",
                    status="reviewed",
                )
                db.add(requirement)
                await db.commit()

            items = parse_historical_test_case_file(
                "legacy-cases.json",
                payload(requirement_external_id),
                max_bytes=100_000,
                max_test_cases=10,
            )
            async with session_factory() as db:
                first = await import_historical_test_cases(
                    db,
                    project_id=project_id,
                    items=items,
                    actor=actor,
                )
                assert first.created_scenario_count == 1
                assert first.created_test_case_count == 1
                assert first.existing_test_case_count == 0
                assert first.queued_vector_count == 1

            async with session_factory() as db:
                second = await import_historical_test_cases(
                    db,
                    project_id=project_id,
                    items=items,
                    actor=actor,
                )
                assert second.created_scenario_count == 0
                assert second.created_test_case_count == 0
                assert second.existing_test_case_count == 1
                assert second.queued_vector_count == 0

                test_case = (
                    await db.execute(
                        select(CaseModel)
                        .join(Requirement, Requirement.id == CaseModel.requirement_id)
                        .where(
                            Requirement.project_id == project_id,
                            CaseModel.external_id == "LEGACY-TC-17",
                        )
                    )
                ).scalar_one()
                version = (
                    await db.execute(
                        select(VersionModel).where(VersionModel.test_case_id == test_case.id)
                    )
                ).scalar_one()
                event = (
                    await db.execute(
                        select(OutboxEvent).where(
                            OutboxEvent.event_type == TEST_CASE_VERSION_INDEX_REQUESTED,
                            OutboxEvent.aggregate_id == version.id,
                        )
                    )
                ).scalar_one()
                assert test_case.source == "historical_import"
                assert test_case.version == 4
                assert test_case.locked is True
                assert version.vector_id == f"test_case:{test_case.id}:v4"
                assert version.approved_by == "legacy-qa-lead"
                assert event.payload["test_case_id"] == str(test_case.id)

                processor = OutboxProcessor(
                    session_factory,
                    config=Settings(_env_file=None),
                    worker_id="historical-loader-test",
                )
                artifact = await processor._load_artifact(db, event)
                assert artifact.vector_id == version.vector_id
                assert artifact.entity_id == str(test_case.id)
                assert artifact.metadata["immutable_version"] is True
                assert artifact.metadata["version"] == 4
                assert "previously consumed" in artifact.text

                case_count = await db.scalar(
                    select(func.count()).select_from(CaseModel).where(CaseModel.id == test_case.id)
                )
                version_count = await db.scalar(
                    select(func.count()).select_from(VersionModel).where(
                        VersionModel.test_case_id == test_case.id
                    )
                )
                assert case_count == 1
                assert version_count == 1

            missing_items = parse_historical_test_case_file(
                "missing.json",
                payload("MISSING-REQUIREMENT"),
                max_bytes=100_000,
                max_test_cases=10,
            )
            async with session_factory() as db:
                before = await db.scalar(select(func.count()).select_from(CaseModel))
                with pytest.raises(HistoricalImportConflictError, match="Requirements must be imported first"):
                    await import_historical_test_cases(
                        db,
                        project_id=project_id,
                        items=missing_items,
                        actor=actor,
                    )
                await db.rollback()
                after = await db.scalar(select(func.count()).select_from(CaseModel))
                assert after == before
        finally:
            if project_id is not None:
                async with session_factory() as db:
                    requirement_ids = select(Requirement.id).where(Requirement.project_id == project_id)
                    case_ids = select(CaseModel.id).where(CaseModel.requirement_id.in_(requirement_ids))
                    scenario_ids = select(ScenarioModel.id).where(
                        ScenarioModel.requirement_id.in_(requirement_ids)
                    )
                    version_ids = select(VersionModel.id).where(
                        VersionModel.test_case_id.in_(case_ids)
                    )
                    await db.execute(delete(OutboxEvent).where(OutboxEvent.aggregate_id.in_(version_ids)))
                    await db.execute(delete(AuditLog).where(AuditLog.actor == actor))
                    await db.execute(delete(ApprovalRecord).where(ApprovalRecord.target_id.in_(case_ids)))
                    await db.execute(delete(IntegrationRun).where(IntegrationRun.requested_by == actor))
                    await db.execute(delete(VersionModel).where(VersionModel.test_case_id.in_(case_ids)))
                    await db.execute(delete(StepModel).where(StepModel.test_case_id.in_(case_ids)))
                    await db.execute(delete(CaseModel).where(CaseModel.id.in_(case_ids)))
                    await db.execute(delete(ScenarioModel).where(ScenarioModel.id.in_(scenario_ids)))
                    await db.execute(delete(Requirement).where(Requirement.id.in_(requirement_ids)))
                    await db.execute(delete(Project).where(Project.id == project_id))
                    await db.commit()
            await engine.dispose()

    asyncio.run(scenario())
