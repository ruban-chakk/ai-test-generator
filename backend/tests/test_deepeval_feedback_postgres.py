import asyncio
import os
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes import create_feedback
from app.core.security import Principal, _principal_context
from app.models import AuditLog, Feedback, OutboxEvent, Project, QualityEvaluation, Requirement
from app.models import TestCase as CaseModel
from app.models import TestScenario as ScenarioModel
from app.schemas import FeedbackCreate


TEST_DSN = os.getenv("TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not TEST_DSN, reason="TEST_POSTGRES_DSN is not configured")


def test_deepeval_feedback_must_link_to_the_same_target() -> None:
    async def scenario() -> None:
        engine = create_async_engine(TEST_DSN)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        ids: dict[str, uuid.UUID] = {}
        token = _principal_context.set(
            Principal(user_id=uuid.uuid4(), username="feedback-admin", role="admin", token_version=1)
        )
        try:
            async with sessions() as db:
                project = Project(name=f"feedback-{uuid.uuid4()}", status="active")
                db.add(project)
                await db.flush()
                requirement = Requirement(
                    project_id=project.id,
                    external_id="FEEDBACK-1",
                    title="Evaluate feedback linkage",
                    description="Link evaluation evidence to feedback for one exact test case.",
                    source="manual",
                )
                db.add(requirement)
                await db.flush()
                test_scenario = ScenarioModel(
                    requirement_id=requirement.id,
                    title="Linked evidence",
                    description="Keep evaluation feedback target-bound.",
                )
                db.add(test_scenario)
                await db.flush()
                test_case = CaseModel(
                    requirement_id=requirement.id,
                    scenario_id=test_scenario.id,
                    title="Revise from evaluation",
                    description="Use linked DeepEval evidence during revision.",
                )
                db.add(test_case)
                await db.flush()
                evaluation = QualityEvaluation(
                    target_level="test_case",
                    target_id=test_case.id,
                    score=55,
                    status="failed",
                    metrics={"deepeval_metrics": [{"name": "correctness", "score": 55}]},
                    issues=[],
                    evaluated_by="feedback-admin",
                )
                db.add(evaluation)
                await db.commit()
                ids.update(
                    project=project.id, requirement=requirement.id, scenario=test_scenario.id,
                    case=test_case.id, evaluation=evaluation.id,
                )

            async with sessions() as db:
                created = await create_feedback(
                    FeedbackCreate(
                        target_level="test_case",
                        target_id=ids["case"],
                        source="deepeval-review",
                        feedback_type="revise",
                        comment="Improve correctness using the linked evidence.",
                        created_by="ignored-client-actor",
                        quality_evaluation_id=ids["evaluation"],
                    ),
                    db,
                )
                ids["feedback"] = created.id
                assert created.quality_evaluation_id == ids["evaluation"]
                assert created.created_by == "feedback-admin"

            async with sessions() as db:
                with pytest.raises(HTTPException) as mismatch:
                    await create_feedback(
                        FeedbackCreate(
                            target_level="requirement",
                            target_id=ids["requirement"],
                            source="deepeval-review",
                            feedback_type="revise",
                            comment="This evaluation belongs to another target.",
                            created_by="feedback-admin",
                            quality_evaluation_id=ids["evaluation"],
                        ),
                        db,
                    )
                assert mismatch.value.status_code == 422
        finally:
            _principal_context.reset(token)
            async with sessions() as db:
                if ids.get("feedback"):
                    await db.execute(delete(OutboxEvent).where(OutboxEvent.aggregate_id == ids["feedback"]))
                    await db.execute(delete(AuditLog).where(AuditLog.entity_id == ids["feedback"]))
                    await db.execute(delete(Feedback).where(Feedback.id == ids["feedback"]))
                if ids.get("evaluation"):
                    await db.execute(delete(QualityEvaluation).where(QualityEvaluation.id == ids["evaluation"]))
                if ids.get("case"):
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
