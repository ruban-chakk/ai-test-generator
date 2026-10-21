import asyncio
import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import (
    ApprovalRecord,
    ImportMappingProfile,
    OutboxEvent,
    Project,
    Requirement,
    TestCase as CaseModel,
    TestCaseStep as StepModel,
    TestCaseVersion as VersionModel,
    TestScenario as ScenarioModel,
    UnresolvedImportRecord,
)
from app.services.historical_ingestion import ParsedHistoricalStep, ParsedHistoricalTestCase
from app.services.unresolved_imports import resolve_unresolved_records, stage_unresolved_test_cases


TEST_DSN = os.getenv("TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not TEST_DSN, reason="TEST_POSTGRES_DSN is not configured")


def test_unresolved_test_case_is_preserved_and_resolves_after_story_arrives() -> None:
    async def scenario() -> None:
        engine = create_async_engine(TEST_DSN)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        project_id: uuid.UUID | None = None
        try:
            async with session_factory() as db:
                project = Project(name=f"unresolved-{uuid.uuid4()}", status="active")
                db.add(project)
                await db.flush()
                project_id = project.id
                profile = ImportMappingProfile(
                    project_id=project.id,
                    name="Historical cases",
                    entity_type="test_case",
                    configuration={"fields": {}, "options": {"unresolved_reference_policy": "stage"}},
                    version=1,
                    active=True,
                    created_by="test",
                )
                db.add(profile)
                await db.flush()
                item = ParsedHistoricalTestCase(
                    external_id="TC-MISSING-1",
                    requirement_external_id="STORY-LATER",
                    scenario_external_id="SC-AUTH",
                    scenario_title="Authentication",
                    scenario_description="Authentication coverage",
                    title="Reject expired token",
                    description="Expired tokens are rejected.",
                    prerequisite=None,
                    priority="high",
                    severity="major",
                    category="security",
                    test_type="negative",
                    status="approved",
                    version=1,
                    approved_at=datetime.now(UTC),
                    source_approved_by="qa",
                    steps=(ParsedHistoricalStep(1, "Submit expired token", "Request is rejected"),),
                    upload_filename="cases.json",
                    upload_sha256="b" * 64,
                    upload_row=1,
                )
                assert await stage_unresolved_test_cases(
                    db,
                    project_id=project.id,
                    profile_id=profile.id,
                    items=[item],
                    actor="test",
                ) == 1
                await db.commit()
                pending = await db.scalar(
                    select(UnresolvedImportRecord).where(
                        UnresolvedImportRecord.project_id == project.id
                    )
                )
                assert pending is not None
                assert pending.status == "pending"

                db.add(
                    Requirement(
                        project_id=project.id,
                        external_id="STORY-LATER",
                        title="Token expiry",
                        description="Tokens expire.",
                        source="mapped_import",
                    )
                )
                await db.flush()
                assert await resolve_unresolved_records(
                    db,
                    project_id=project.id,
                    actor="test",
                    references={"STORY-LATER"},
                ) == (1, 0)
                await db.commit()
                await db.refresh(pending)
                assert pending.status == "resolved"
                assert await db.scalar(
                    select(CaseModel).where(CaseModel.external_id == "TC-MISSING-1")
                ) is not None
        finally:
            if project_id:
                async with session_factory() as db:
                    requirement_ids = select(Requirement.id).where(Requirement.project_id == project_id)
                    case_ids = select(CaseModel.id).where(CaseModel.requirement_id.in_(requirement_ids))
                    scenario_ids = select(ScenarioModel.id).where(ScenarioModel.requirement_id.in_(requirement_ids))
                    version_ids = select(VersionModel.id).where(VersionModel.requirement_id.in_(requirement_ids))
                    await db.execute(delete(OutboxEvent).where(OutboxEvent.aggregate_id.in_(version_ids)))
                    await db.execute(delete(ApprovalRecord).where(ApprovalRecord.target_id.in_(case_ids)))
                    await db.execute(delete(StepModel).where(StepModel.test_case_id.in_(case_ids)))
                    await db.execute(delete(VersionModel).where(VersionModel.requirement_id.in_(requirement_ids)))
                    await db.execute(delete(CaseModel).where(CaseModel.requirement_id.in_(requirement_ids)))
                    await db.execute(delete(ScenarioModel).where(ScenarioModel.id.in_(scenario_ids)))
                    await db.execute(delete(UnresolvedImportRecord).where(UnresolvedImportRecord.project_id == project_id))
                    await db.execute(delete(Requirement).where(Requirement.project_id == project_id))
                    await db.execute(delete(ImportMappingProfile).where(ImportMappingProfile.project_id == project_id))
                    await db.execute(delete(Project).where(Project.id == project_id))
                    await db.commit()
            await engine.dispose()

    asyncio.run(scenario())
