import asyncio
import os
import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes import queue_test_executions
from app.core.security import Principal, _principal_context
from app.models import (
    AuditLog,
    OutboxEvent,
    Project,
    Requirement,
    TestCase as CaseModel,
    TestCaseStep as StepModel,
    TestExecutionRun as ExecutionRunModel,
    TestScenario as ScenarioModel,
)
from app.schemas import TestExecutionRequest as ExecutionRequest


TEST_DSN = os.getenv("TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not TEST_DSN, reason="TEST_POSTGRES_DSN is not configured")


def test_execution_queue_is_project_scoped_and_request_idempotent() -> None:
    async def scenario() -> None:
        engine = create_async_engine(TEST_DSN)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        project_id: uuid.UUID | None = None
        token = _principal_context.set(
            Principal(user_id=uuid.uuid4(), username="execution-admin", role="admin", token_version=1)
        )
        try:
            async with session_factory() as db:
                project = Project(name=f"execution-project-{uuid.uuid4()}", status="active")
                db.add(project)
                await db.flush()
                project_id = project.id
                requirement = Requirement(
                    project_id=project.id,
                    title="Password reset",
                    description="Reset credentials with an expiring token.",
                    source="manual",
                    status="approved",
                )
                db.add(requirement)
                await db.flush()
                test_scenario = ScenarioModel(
                    requirement_id=requirement.id,
                    title="Expired token",
                    description="Verify expiry enforcement.",
                    status="approved",
                )
                db.add(test_scenario)
                await db.flush()
                test_case = CaseModel(
                    scenario_id=test_scenario.id,
                    requirement_id=requirement.id,
                    title="Reject expired token",
                    description="Expired tokens are rejected.",
                    status="approved",
                    version=2,
                )
                db.add(test_case)
                await db.flush()
                db.add(
                    StepModel(
                        test_case_id=test_case.id,
                        step_number=1,
                        action="Open expired token",
                        expected_result="Access is rejected",
                    )
                )
                await db.commit()

                request_id = uuid.uuid4()
                payload = ExecutionRequest(
                    project_id=project.id,
                    test_case_ids=[test_case.id, test_case.id],
                    environment="staging",
                    request_id=request_id,
                )
                first = await queue_test_executions(payload, db)
                second = await queue_test_executions(payload, db)
                assert len(first) == len(second) == 1
                assert first[0].id == second[0].id
                assert first[0].test_case_version == 2
                assert first[0].status == "queued"

                runs = (
                    await db.execute(
                        select(ExecutionRunModel).where(ExecutionRunModel.project_id == project.id)
                    )
                ).scalars().all()
                events = (
                    await db.execute(
                        select(OutboxEvent).where(
                            OutboxEvent.aggregate_type == "test_execution_run",
                            OutboxEvent.aggregate_id == first[0].id,
                        )
                    )
                ).scalars().all()
                assert len(runs) == 1
                assert len(events) == 1
        finally:
            _principal_context.reset(token)
            if project_id:
                async with session_factory() as db:
                    requirement_ids = select(Requirement.id).where(Requirement.project_id == project_id)
                    scenario_ids = select(ScenarioModel.id).where(ScenarioModel.requirement_id.in_(requirement_ids))
                    case_ids = select(CaseModel.id).where(CaseModel.requirement_id.in_(requirement_ids))
                    run_ids = select(ExecutionRunModel.id).where(ExecutionRunModel.project_id == project_id)
                    await db.execute(delete(AuditLog).where(AuditLog.entity_id == project_id))
                    await db.execute(delete(OutboxEvent).where(OutboxEvent.aggregate_id.in_(run_ids)))
                    await db.execute(delete(ExecutionRunModel).where(ExecutionRunModel.project_id == project_id))
                    await db.execute(delete(StepModel).where(StepModel.test_case_id.in_(case_ids)))
                    await db.execute(delete(CaseModel).where(CaseModel.id.in_(case_ids)))
                    await db.execute(delete(ScenarioModel).where(ScenarioModel.id.in_(scenario_ids)))
                    await db.execute(delete(Requirement).where(Requirement.id.in_(requirement_ids)))
                    await db.execute(delete(Project).where(Project.id == project_id))
                    await db.commit()
            await engine.dispose()

    asyncio.run(scenario())
