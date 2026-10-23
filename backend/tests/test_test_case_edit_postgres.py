import asyncio
import os
import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes import update_test_case
from app.core.security import Principal, _principal_context
from app.models import (
    AuditLog,
    OutboxEvent,
    Project,
    Requirement,
    TestCase as CaseModel,
    TestCaseStep as StepModel,
    TestScenario as ScenarioModel,
)
from app.schemas import TestCaseStep as StepPayload
from app.schemas import TestCaseUpdate as CaseUpdatePayload
from app.services.outbox import TEST_CASE_QUALITY_EVALUATION_REQUESTED


TEST_DSN = os.getenv("TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not TEST_DSN, reason="TEST_POSTGRES_DSN is not configured")


def test_manual_edit_creates_new_draft_and_automatic_evaluation_event() -> None:
    async def scenario() -> None:
        engine = create_async_engine(TEST_DSN)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        ids: dict[str, uuid.UUID] = {}
        principal_token = _principal_context.set(
            Principal(user_id=uuid.uuid4(), username="manual-editor", role="admin", token_version=1)
        )
        try:
            async with session_factory() as db:
                project = Project(name=f"manual-edit-{uuid.uuid4()}", status="active")
                db.add(project)
                await db.flush()
                requirement = Requirement(
                    project_id=project.id,
                    title="Editable approved requirement",
                    description="Allow a governed manual edit without mutating an approved snapshot.",
                    source="manual",
                    status="generated",
                )
                db.add(requirement)
                await db.flush()
                test_scenario = ScenarioModel(
                    requirement_id=requirement.id,
                    title="Editable scenario",
                    description="A scenario containing an editable test case.",
                    status="draft",
                )
                db.add(test_scenario)
                await db.flush()
                test_case = CaseModel(
                    scenario_id=test_scenario.id,
                    requirement_id=requirement.id,
                    title="Original approved case",
                    description="An approved case that will become a new draft version.",
                    priority="high",
                    severity="major",
                    status="approved",
                    version=1,
                    locked=True,
                    repository_status="indexed",
                )
                db.add(test_case)
                await db.flush()
                db.add(
                    StepModel(
                        test_case_id=test_case.id,
                        step_number=1,
                        action="Perform the original action.",
                        expected_result="Observe the original result.",
                    )
                )
                await db.commit()
                ids = {
                    "project": project.id,
                    "requirement": requirement.id,
                    "scenario": test_scenario.id,
                    "case": test_case.id,
                }

            async with session_factory() as db:
                updated = await update_test_case(
                    str(ids["case"]),
                    CaseUpdatePayload(
                        expected_version=1,
                        title="Manually updated approved case",
                        description="The approved case is now a governed second draft version.",
                        priority="critical",
                        severity="major",
                        steps=[
                            StepPayload(
                                step_number=1,
                                action="Perform the manually updated action.",
                                expected_result="Observe the manually updated result.",
                            )
                        ],
                    ),
                    db,
                )
                assert updated.version == 2
                assert updated.status == "draft"
                assert updated.locked is False
                assert updated.repository_status == "draft"
                event = await db.scalar(
                    select(OutboxEvent).where(
                        OutboxEvent.aggregate_id == ids["case"],
                        OutboxEvent.event_type == TEST_CASE_QUALITY_EVALUATION_REQUESTED,
                    )
                )
                assert event is not None
                assert event.event_key.endswith(":v2")
                assert event.payload["requested_by"] == "manual-editor"
        finally:
            _principal_context.reset(principal_token)
            async with session_factory() as db:
                if ids.get("case"):
                    await db.execute(delete(OutboxEvent).where(OutboxEvent.aggregate_id == ids["case"]))
                    await db.execute(delete(AuditLog).where(AuditLog.entity_id == ids["case"]))
                    await db.execute(delete(StepModel).where(StepModel.test_case_id == ids["case"]))
                    await db.execute(delete(CaseModel).where(CaseModel.id == ids["case"]))
                if ids.get("scenario"):
                    await db.execute(delete(ScenarioModel).where(ScenarioModel.id == ids["scenario"]))
                if ids.get("requirement"):
                    await db.execute(delete(Requirement).where(Requirement.id == ids["requirement"]))
                if ids.get("project"):
                    await db.execute(delete(Project).where(Project.id == ids["project"]))
                await db.commit()
            await engine.dispose()

    asyncio.run(scenario())
