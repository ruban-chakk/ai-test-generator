import asyncio
import os
import uuid

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes import generate_requirement_draft
from app.core.security import Principal, _principal_context
from app.models import (
    Project,
    Requirement,
    TestCase as CaseModel,
    TestCaseStep as StepModel,
    TestScenario as ScenarioModel,
)
from app.schemas import RequirementDetail


TEST_DSN = os.getenv("TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not TEST_DSN, reason="TEST_POSTGRES_DSN is not configured")


def test_generate_existing_draft_returns_fully_loaded_requirement() -> None:
    async def scenario() -> None:
        engine = create_async_engine(TEST_DSN)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        project_id: uuid.UUID | None = None
        requirement_id: uuid.UUID | None = None
        scenario_id: uuid.UUID | None = None
        test_case_id: uuid.UUID | None = None
        principal_token = _principal_context.set(
            Principal(
                user_id=uuid.uuid4(),
                username="generation-route-admin",
                role="admin",
                token_version=1,
            )
        )
        try:
            async with session_factory() as db:
                project = Project(name=f"generation-route-{uuid.uuid4()}", status="active")
                db.add(project)
                await db.flush()
                project_id = project.id

                requirement = Requirement(
                    project_id=project.id,
                    external_id="GEN-EXISTING-1",
                    title="Existing generated requirement",
                    description="Return the existing generated hierarchy without calling the provider.",
                    source="manual",
                    status="generated",
                )
                db.add(requirement)
                await db.flush()
                requirement_id = requirement.id

                test_scenario = ScenarioModel(
                    requirement_id=requirement.id,
                    title="Existing scenario",
                    description="A scenario created by an earlier generation request.",
                    status="draft",
                )
                db.add(test_scenario)
                await db.flush()
                scenario_id = test_scenario.id

                test_case = CaseModel(
                    scenario_id=test_scenario.id,
                    requirement_id=requirement.id,
                    title="Existing test case",
                    description="A case that must be included in the idempotent response.",
                    status="draft",
                )
                db.add(test_case)
                await db.flush()
                test_case_id = test_case.id
                db.add(
                    StepModel(
                        test_case_id=test_case.id,
                        step_number=1,
                        action="Request generation again.",
                        expected_result="The existing hierarchy is returned.",
                    )
                )
                await db.commit()

            async with session_factory() as db:
                returned = await generate_requirement_draft(str(requirement_id), db)
                response = RequirementDetail.model_validate(returned)
                assert response.scenarios is not None
                assert len(response.scenarios) == 1
                assert response.scenarios[0].test_cases is not None
                assert len(response.scenarios[0].test_cases) == 1
                assert response.scenarios[0].test_cases[0].steps is not None
                assert len(response.scenarios[0].test_cases[0].steps) == 1
        finally:
            _principal_context.reset(principal_token)
            async with session_factory() as db:
                if test_case_id:
                    await db.execute(delete(StepModel).where(StepModel.test_case_id == test_case_id))
                    await db.execute(delete(CaseModel).where(CaseModel.id == test_case_id))
                if scenario_id:
                    await db.execute(delete(ScenarioModel).where(ScenarioModel.id == scenario_id))
                if requirement_id:
                    await db.execute(delete(Requirement).where(Requirement.id == requirement_id))
                if project_id:
                    await db.execute(delete(Project).where(Project.id == project_id))
                await db.commit()
            await engine.dispose()

    asyncio.run(scenario())
