import asyncio
import os
import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes import (
    get_search_analytics,
    get_custom_field_facets,
    list_saved_searches,
    record_search_judgment,
    save_search,
    semantic_search,
)
from app.core.security import Principal, _principal_context
from app.models import (
    Feedback,
    Project,
    Requirement,
    SavedSearch,
    SearchEvent,
    SearchJudgment,
    TestCase as CaseModel,
    TestCaseStep as StepModel,
    TestScenario as ScenarioModel,
)
from app.schemas import SavedSearchCreate, SearchJudgmentCreate
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
                    metadata_json={"custom_fields": {"risk": "high"}},
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
                draft_test_case = CaseModel(
                    scenario_id=test_scenario.id,
                    requirement_id=requirement.id,
                    title="Draft expired reset token coverage",
                    description="Unapproved coverage for an expired token.",
                    status="draft",
                    locked=False,
                )
                db.add(draft_test_case)
                await db.flush()
                db.add(
                    StepModel(
                        test_case_id=test_case.id,
                        step_number=1,
                        action="Complete the captcha challenge and submit the expired token.",
                        expected_result="The token is rejected without changing credentials.",
                    )
                )
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

                step_matches = await service.search(
                    "captcha challenge",
                    project_id=str(project.id),
                    entity_type="test_case",
                    limit=10,
                )
                assert [match.entity_id for match in step_matches] == [str(test_case.id)]
                assert "steps" in step_matches[0].matched_fields

                scenario_matches = await service.search(
                    "Recovery security",
                    project_id=str(project.id),
                    entity_type="test_case",
                    limit=10,
                )
                assert {match.entity_id for match in scenario_matches} == {
                    str(test_case.id), str(draft_test_case.id)
                }
                assert "scenario" in scenario_matches[0].matched_fields

                approved_matches = await service.search(
                    "expired token",
                    project_id=str(project.id),
                    entity_type="test_case",
                    test_case_approval="approved",
                    limit=10,
                )
                assert [match.entity_id for match in approved_matches] == [str(test_case.id)]

                unapproved_matches = await service.search(
                    "expired token",
                    project_id=str(project.id),
                    entity_type="test_case",
                    test_case_approval="unapproved",
                    limit=10,
                )
                assert [match.entity_id for match in unapproved_matches] == [str(draft_test_case.id)]

                custom_matches = await service.search(
                    "expired token",
                    project_id=str(project.id),
                    entity_type="requirement",
                    custom_field="risk",
                    custom_value="high",
                    limit=10,
                )
                assert [match.entity_id for match in custom_matches] == [str(requirement.id)]
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
                                await db.execute(delete(StepModel).where(StepModel.test_case_id.in_(test_case_ids)))
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


def test_search_pagination_saved_searches_and_relevance_analytics() -> None:
    async def scenario() -> None:
        engine = create_async_engine(TEST_DSN)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        project_id: uuid.UUID | None = None
        token = _principal_context.set(
            Principal(user_id=uuid.uuid4(), username="search-admin", role="admin", token_version=1)
        )
        try:
            async with session_factory() as db:
                project = Project(name=f"search-learning-{uuid.uuid4()}", status="active")
                db.add(project)
                await db.flush()
                project_id = project.id
                db.add_all(
                    [
                        Requirement(
                            project_id=project.id,
                            external_id=f"SEARCH-{index}",
                            title=f"Token validation case {index}",
                            description="Validate expiring authentication tokens safely.",
                            source="manual",
                            status="approved",
                            metadata_json={"custom_fields": {"risk": "high"}},
                        )
                        for index in range(3)
                    ]
                )
                await db.commit()

                first_page = await semantic_search(
                    project_id=project.id,
                    query="validating tokens",
                    entity_type="requirement",
                    limit=2,
                    offset=0,
                    mode="keyword",
                    db=db,
                )
                second_page = await semantic_search(
                    project_id=project.id,
                    query="validating tokens",
                    entity_type="requirement",
                    limit=2,
                    offset=2,
                    mode="keyword",
                    db=db,
                )
                assert len(first_page) == 2
                assert len(second_page) == 1
                assert {item.entity_id for item in first_page}.isdisjoint(
                    {item.entity_id for item in second_page}
                )

                event_id = uuid.UUID(first_page[0].metadata["search_event_id"])
                await record_search_judgment(
                    SearchJudgmentCreate(
                        search_event_id=event_id,
                        entity_type="requirement",
                        entity_id=first_page[0].entity_id,
                        rank=1,
                        judgment="relevant",
                    ),
                    db,
                )
                await save_search(
                    SavedSearchCreate(
                        project_id=project.id,
                        name="Token checks",
                        query="validating tokens",
                        mode="keyword",
                        entity_type="requirement",
                    ),
                    db,
                )
                assert len(await list_saved_searches(project.id, db)) == 1
                analytics = await get_search_analytics(project.id, db)
                assert analytics.query_count == 2
                assert analytics.judgments == {"relevant": 1}
                facets = await get_custom_field_facets(project.id, "risk", db)
                assert facets.values == [{"value": "high", "count": 3}]
        finally:
            _principal_context.reset(token)
            if project_id:
                async with session_factory() as db:
                    event_ids = select(SearchEvent.id).where(SearchEvent.project_id == project_id)
                    await db.execute(delete(SearchJudgment).where(SearchJudgment.search_event_id.in_(event_ids)))
                    await db.execute(delete(SearchEvent).where(SearchEvent.project_id == project_id))
                    await db.execute(delete(SavedSearch).where(SavedSearch.project_id == project_id))
                    await db.execute(delete(Requirement).where(Requirement.project_id == project_id))
                    await db.execute(delete(Project).where(Project.id == project_id))
                    await db.commit()
            await engine.dispose()

    asyncio.run(scenario())
