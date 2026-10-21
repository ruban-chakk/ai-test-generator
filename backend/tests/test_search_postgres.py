import asyncio
import os
import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Feedback, Project, Requirement, TestCase as CaseModel, TestScenario as ScenarioModel
from app.services.search import KeywordSearchService


TEST_DSN = os.getenv("TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not TEST_DSN, reason="TEST_POSTGRES_DSN is not configured")


def test_keyword_search_is_project_scoped_and_searches_canonical_artifacts() -> None:
    async def scenario() -> None:
        engine = create_async_engine(TEST_DSN)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        project_id: uuid.UUID | None = None
        other_project_id: uuid.UUID | None = None
        try:
            async with session_factory() as db:
                project = Project(name=f"search-{uuid.uuid4()}", status="active")
                other_project = Project(name=f"search-other-{uuid.uuid4()}", status="active")
                db.add_all([project, other_project])
                await db.flush()
                project_id = project.id
                other_project_id = other_project.id

                requirement = Requirement(
                    project_id=project.id,
                    external_id="AUTH-401",
                    title="Expired reset token",
                    description="An expired reset token must never change credentials.",
                    source="manual",
                    status="approved",
                )
                hidden_requirement = Requirement(
                    project_id=other_project.id,
                    external_id="AUTH-401-HIDDEN",
                    title="Expired reset token from another project",
                    description="Must not leak across project boundaries.",
                    source="manual",
                    status="approved",
                )
                db.add_all([requirement, hidden_requirement])
                await db.flush()
                test_scenario = ScenarioModel(
                    requirement_id=requirement.id,
                    title="Password recovery",
                    description="Recovery security scenarios",
                    status="approved",
                )
                db.add(test_scenario)
                await db.flush()
                test_case = CaseModel(
                    scenario_id=test_scenario.id,
                    requirement_id=requirement.id,
                    title="Reject an expired reset token",
                    description="Verify that credentials remain unchanged.",
                    status="approved",
                    locked=True,
                )
                db.add(test_case)
                await db.flush()
                feedback = Feedback(
                    target_level="test_case",
                    target_id=test_case.id,
                    source="user",
                    feedback_type="revise",
                    comment="Include an audit event when the expired token is rejected.",
                    created_by="search-test",
                )
                db.add(feedback)
                await db.commit()

                service = KeywordSearchService(db)
                exact = await service.search("AUTH-401", project_id=str(project.id), limit=10)
                assert [match.entity_id for match in exact] == [str(requirement.id)]
                assert exact[0].matched_fields == ("external ID",)

                matches = await service.search("expired token", project_id=str(project.id), limit=10)
                assert {match.entity_type for match in matches} == {"requirement", "test_case", "feedback"}
                assert all(match.entity_id != str(hidden_requirement.id) for match in matches)
                feedback_match = next(match for match in matches if match.entity_type == "feedback")
                assert feedback_match.metadata["requirement_id"] == str(requirement.id)
        finally:
            if project_id or other_project_id:
                async with session_factory() as db:
                    if project_id:
                        requirement_ids = [
                            item
                            for item in (
                                await db.execute(select(Requirement.id).where(Requirement.project_id == project_id))
                            ).scalars()
                        ]
                        if requirement_ids:
                            scenario_ids = [
                                item
                                for item in (
                                    await db.execute(
                                        select(ScenarioModel.id).where(
                                            ScenarioModel.requirement_id.in_(requirement_ids)
                                        )
                                    )
                                ).scalars()
                            ]
                            test_case_ids = [
                                item
                                for item in (
                                    await db.execute(
                                        select(CaseModel.id).where(
                                            CaseModel.requirement_id.in_(requirement_ids)
                                        )
                                    )
                                ).scalars()
                            ]
                            if test_case_ids:
                                await db.execute(delete(Feedback).where(Feedback.target_id.in_(test_case_ids)))
                            await db.execute(
                                delete(CaseModel).where(CaseModel.requirement_id.in_(requirement_ids))
                            )
                            if scenario_ids:
                                await db.execute(
                                    delete(ScenarioModel).where(ScenarioModel.id.in_(scenario_ids))
                                )
                            await db.execute(delete(Requirement).where(Requirement.id.in_(requirement_ids)))
                    if other_project_id:
                        await db.execute(delete(Requirement).where(Requirement.project_id == other_project_id))
                    await db.execute(delete(Project).where(Project.id.in_([project_id, other_project_id])))
                    await db.commit()
            await engine.dispose()

    asyncio.run(scenario())
