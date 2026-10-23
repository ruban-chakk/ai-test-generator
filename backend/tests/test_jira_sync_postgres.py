import asyncio
import os
import uuid

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import AuditLog, IntegrationRun, OutboxEvent, Project, Requirement, RequirementVersion
from app.services.integrations import JiraIssue
from app.services.jira_sync import sync_jira_requirements


TEST_DSN = os.getenv("TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not TEST_DSN, reason="TEST_POSTGRES_DSN is not configured")


class FakeJiraClient:
    async def search_issues(self, jql: str, max_results: int) -> list[JiraIssue]:
        assert jql == "project = QA ORDER BY updated DESC"
        assert max_results == 100
        return [
            JiraIssue(
                key="QA-501",
                summary="Rotate expired credentials",
                description="The system must reject expired credentials and record an audit event.",
                issue_type="Story",
                status="Ready",
                updated="2026-10-22T01:00:00Z",
            )
        ]


def test_jira_delta_sync_creates_then_leaves_unchanged_requirement() -> None:
    async def scenario() -> None:
        engine = create_async_engine(TEST_DSN)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        project_id: uuid.UUID | None = None
        try:
            async with session_factory() as db:
                project = Project(name=f"jira-sync-{uuid.uuid4()}", status="active")
                db.add(project)
                await db.commit()
                project_id = project.id

                first = await sync_jira_requirements(
                    db,
                    project_id=project.id,
                    jql="project = QA ORDER BY updated DESC",
                    max_results=100,
                    actor="schedule:test",
                    client=FakeJiraClient(),
                )
                second = await sync_jira_requirements(
                    db,
                    project_id=project.id,
                    jql="project = QA ORDER BY updated DESC",
                    max_results=100,
                    actor="schedule:test",
                    client=FakeJiraClient(),
                )
                assert first.result["created_count"] == 1
                assert second.result["unchanged_count"] == 1
                assert await db.scalar(
                    select(func.count()).select_from(Requirement).where(
                        Requirement.project_id == project.id
                    )
                ) == 1
                assert await db.scalar(
                    select(func.count()).select_from(RequirementVersion).where(
                        RequirementVersion.project_id == project.id
                    )
                ) == 1
        finally:
            if project_id:
                async with session_factory() as db:
                    version_ids = select(RequirementVersion.id).where(
                        RequirementVersion.project_id == project_id
                    )
                    run_ids = select(IntegrationRun.id).where(
                        IntegrationRun.requested_by == "schedule:test"
                    )
                    await db.execute(delete(OutboxEvent).where(OutboxEvent.aggregate_id.in_(version_ids)))
                    await db.execute(delete(AuditLog).where(AuditLog.entity_id.in_(run_ids)))
                    await db.execute(delete(IntegrationRun).where(IntegrationRun.id.in_(run_ids)))
                    await db.execute(delete(RequirementVersion).where(RequirementVersion.project_id == project_id))
                    await db.execute(delete(Requirement).where(Requirement.project_id == project_id))
                    await db.execute(delete(Project).where(Project.id == project_id))
                    await db.commit()
            await engine.dispose()

    asyncio.run(scenario())
