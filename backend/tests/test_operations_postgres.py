import asyncio
import io
import os
import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.datastructures import Headers, UploadFile

from app.api.routes import import_requirement_file, retry_outbox_event
from app.core.security import Principal, _principal_context
from app.models import AuditLog, IntegrationRun, OutboxEvent, Project, Requirement, RequirementVersion


TEST_DSN = os.getenv("TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not TEST_DSN, reason="TEST_POSTGRES_DSN is not configured")


def test_file_import_is_atomic_idempotent_and_queues_indexing() -> None:
    async def scenario() -> None:
        engine = create_async_engine(TEST_DSN)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        project_id: uuid.UUID | None = None
        event_id: uuid.UUID | None = None
        run_ids: list[uuid.UUID] = []
        token = _principal_context.set(
            Principal(user_id=uuid.uuid4(), username="operations-admin", role="admin", token_version=1)
        )
        try:
            async with session_factory() as db:
                project = Project(name=f"file-import-{uuid.uuid4()}", status="active")
                db.add(project)
                await db.commit()
                await db.refresh(project)
                project_id = project.id

                def upload() -> UploadFile:
                    return UploadFile(
                        filename="requirements.csv",
                        file=io.BytesIO(
                            b"external_id,title,description\nAUTH-101,Password reset,Users can reset a forgotten password\n"
                        ),
                        headers=Headers({"content-type": "text/csv"}),
                    )

                first = await import_requirement_file(project.id, upload(), db)
                second = await import_requirement_file(project.id, upload(), db)
                run_ids = [first.id, second.id]
                assert first.result["created_count"] == 1
                assert second.result["created_count"] == 0
                assert second.result["existing_count"] == 1

                requirements = (
                    await db.execute(select(Requirement).where(Requirement.project_id == project.id))
                ).scalars().all()
                assert len(requirements) == 1
                assert requirements[0].external_id == "AUTH-101"
                assert requirements[0].metadata_json["upload_filename"] == "requirements.csv"
                versions = (
                    await db.execute(
                        select(RequirementVersion).where(
                            RequirementVersion.requirement_id == requirements[0].id
                        )
                    )
                ).scalars().all()
                assert len(versions) == 1
                events = (
                    await db.execute(select(OutboxEvent).where(OutboxEvent.aggregate_id == versions[0].id))
                ).scalars().all()
                assert len(events) == 1
                event_id = events[0].id
                assert events[0].payload == {
                    "schema_version": 1,
                    "requirement_id": str(requirements[0].id),
                    "version": 1,
                }

                events[0].status = "failed"
                events[0].attempts = 8
                events[0].last_error = "GenerationProviderError"
                await db.commit()
                retried = await retry_outbox_event(events[0].id, db)
                assert retried.status == "pending"
                assert retried.attempts == 0
                assert retried.last_error is None
        finally:
            _principal_context.reset(token)
            if project_id:
                async with session_factory() as db:
                    requirement_ids = select(Requirement.id).where(Requirement.project_id == project_id)
                    version_ids = select(RequirementVersion.id).where(
                        RequirementVersion.requirement_id.in_(requirement_ids)
                    )
                    await db.execute(delete(AuditLog).where(AuditLog.entity_id.in_(run_ids)))
                    if event_id:
                        await db.execute(delete(AuditLog).where(AuditLog.entity_id == event_id))
                    await db.execute(delete(OutboxEvent).where(OutboxEvent.aggregate_id.in_(version_ids)))
                    await db.execute(delete(Requirement).where(Requirement.project_id == project_id))
                    await db.execute(delete(IntegrationRun).where(IntegrationRun.id.in_(run_ids)))
                    await db.execute(delete(Project).where(Project.id == project_id))
                    await db.commit()
            await engine.dispose()

    asyncio.run(scenario())
