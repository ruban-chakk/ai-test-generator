import asyncio
import os
import uuid

import pytest
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import (
    AuditLog,
    Feedback,
    IntegrationRun,
    OutboxEvent,
    Project,
    Requirement,
    TestCase as CaseModel,
    TestCaseStep as StepModel,
    TestCaseVersion as VersionModel,
    TestScenario as ScenarioModel,
)
from app.services.vector_backfill import enqueue_vector_backfill


TEST_DSN = os.getenv("TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not TEST_DSN, reason="TEST_POSTGRES_DSN is not configured")


def test_vector_backfill_is_project_scoped_and_idempotent() -> None:
    async def scenario() -> None:
        engine = create_async_engine(TEST_DSN)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        project_id: uuid.UUID | None = None
        other_project_id: uuid.UUID | None = None
        try:
            async with session_factory() as db:
                project = Project(name=f"backfill-{uuid.uuid4()}", status="active")
                other_project = Project(name=f"backfill-other-{uuid.uuid4()}", status="active")
                db.add_all([project, other_project])
                await db.flush()
                project_id = project.id
                other_project_id = other_project.id
                requirement = Requirement(
                    project_id=project.id,
                    title="Historical password reset",
                    description="Users must reset a forgotten password using a single-use link.",
                    source="upload",
                    status="reviewed",
                )
                other_requirement = Requirement(
                    project_id=other_project.id,
                    title="Unrelated project requirement",
                    description="This record must not be selected by the scoped backfill.",
                    source="manual",
                    status="draft",
                )
                db.add_all([requirement, other_requirement])
                await db.flush()
                test_scenario = ScenarioModel(
                    requirement_id=requirement.id,
                    title="Reset link validation",
                    description="Validate single-use password reset behavior.",
                    status="approved",
                )
                db.add(test_scenario)
                await db.flush()
                test_case = CaseModel(
                    scenario_id=test_scenario.id,
                    requirement_id=requirement.id,
                    title="Reject reused password reset link",
                    description="A previously consumed reset link must not change credentials.",
                    priority="high",
                    severity="major",
                    status="approved",
                    version=2,
                    repository_status="draft",
                )
                db.add(test_case)
                await db.flush()
                db.add(
                    StepModel(
                        test_case_id=test_case.id,
                        step_number=1,
                        action="Open a previously consumed password reset link.",
                        expected_result="The application rejects the link without changing credentials.",
                    )
                )
                version = VersionModel(
                    test_case_id=test_case.id,
                    requirement_id=requirement.id,
                    scenario_id=test_scenario.id,
                    version=2,
                    source="generated",
                    title=test_case.title,
                    description=test_case.description,
                    priority="high",
                    severity="major",
                    status="approved",
                    approved_by="approver",
                    steps_snapshot=[
                        {
                            "step_number": 1,
                            "action": "Open a previously consumed password reset link.",
                            "expected_result": "The application rejects the link without changing credentials.",
                        }
                    ],
                )
                db.add(version)
                feedback = Feedback(
                    target_level="test_case",
                    target_id=test_case.id,
                    source="user",
                    feedback_type="accept",
                    comment="Retain this historical regression case.",
                    created_by="reviewer",
                )
                db.add(feedback)
                await db.commit()
                requirement_id = requirement.id
                other_requirement_id = other_requirement.id
                test_case_id = test_case.id
                version_id = version.id
                feedback_id = feedback.id

            async with session_factory() as db:
                first = await enqueue_vector_backfill(
                    db,
                    project_id=project_id,
                    actor="backfill-test",
                )
                assert first.candidate_count == 3
                assert first.queued_count == 3
                assert first.requeued_count == 0

            async with session_factory() as db:
                second = await enqueue_vector_backfill(
                    db,
                    project_id=project_id,
                    actor="backfill-test",
                )
                assert second.candidate_count == 3
                assert second.queued_count == 0
                assert second.in_flight_count == 3

                requirement = await db.get(Requirement, requirement_id)
                other_requirement = await db.get(Requirement, other_requirement_id)
                test_case = await db.get(CaseModel, test_case_id)
                feedback = await db.get(Feedback, feedback_id)
                assert requirement.vector_id == f"requirement:{requirement_id}:v1"
                assert other_requirement.vector_id is None
                assert test_case.vector_id == f"test_case:{test_case_id}:v2"
                assert test_case.repository_status == "pending_index"
                assert feedback.vector_id == f"feedback:{feedback_id}"
                events = (
                    await db.execute(
                        select(OutboxEvent).where(
                            OutboxEvent.aggregate_id.in_([requirement_id, version_id, feedback_id])
                        )
                    )
                ).scalars().all()
                assert len(events) == 3

                for event in events:
                    event.status = "completed"
                await db.commit()

            async with session_factory() as db:
                forced = await enqueue_vector_backfill(
                    db,
                    project_id=project_id,
                    include_all=True,
                    actor="backfill-test",
                )
                assert forced.candidate_count == 3
                assert forced.requeued_count == 3
                assert forced.queued_count == 0
        finally:
            if project_id is not None and other_project_id is not None:
                async with session_factory() as db:
                    requirement_ids = select(Requirement.id).where(
                        Requirement.project_id.in_([project_id, other_project_id])
                    )
                    test_case_ids = select(CaseModel.id).where(CaseModel.requirement_id.in_(requirement_ids))
                    scenario_ids = select(ScenarioModel.id).where(ScenarioModel.requirement_id.in_(requirement_ids))
                    feedback_ids = select(Feedback.id).where(Feedback.target_id.in_(test_case_ids))
                    version_ids = select(VersionModel.id).where(VersionModel.test_case_id.in_(test_case_ids))
                    await db.execute(
                        delete(OutboxEvent).where(
                            or_(
                                OutboxEvent.aggregate_id.in_(requirement_ids),
                                OutboxEvent.aggregate_id.in_(test_case_ids),
                                OutboxEvent.aggregate_id.in_(feedback_ids),
                                OutboxEvent.aggregate_id.in_(version_ids),
                            )
                        )
                    )
                    await db.execute(delete(AuditLog).where(AuditLog.actor == "backfill-test"))
                    await db.execute(delete(IntegrationRun).where(IntegrationRun.requested_by == "backfill-test"))
                    await db.execute(delete(Feedback).where(Feedback.target_id.in_(test_case_ids)))
                    await db.execute(delete(VersionModel).where(VersionModel.test_case_id.in_(test_case_ids)))
                    await db.execute(delete(StepModel).where(StepModel.test_case_id.in_(test_case_ids)))
                    await db.execute(delete(CaseModel).where(CaseModel.id.in_(test_case_ids)))
                    await db.execute(delete(ScenarioModel).where(ScenarioModel.id.in_(scenario_ids)))
                    await db.execute(delete(Requirement).where(Requirement.id.in_(requirement_ids)))
                    await db.execute(delete(Project).where(Project.id.in_([project_id, other_project_id])))
                    await db.commit()
            await engine.dispose()

    asyncio.run(scenario())
