import asyncio
import os
import uuid

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes import acknowledge_alert, list_alerts
from app.core.config import Settings
from app.core.security import Principal, _principal_context
from app.models import Alert, AuditLog, Project
from app.services.alerts import create_alert


TEST_DSN = os.getenv("TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not TEST_DSN, reason="TEST_POSTGRES_DSN is not configured")


def test_alert_deduplication_listing_and_acknowledgement_are_durable() -> None:
    async def scenario() -> None:
        engine = create_async_engine(TEST_DSN)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        project_id: uuid.UUID | None = None
        alert_id: uuid.UUID | None = None
        token = _principal_context.set(
            Principal(user_id=uuid.uuid4(), username="alert-admin", role="admin", token_version=1)
        )
        try:
            async with session_factory() as db:
                project = Project(name=f"alert-project-{uuid.uuid4()}", status="active")
                db.add(project)
                await db.flush()
                project_id = project.id
                first = await create_alert(
                    db,
                    dedupe_key=f"failure-{uuid.uuid4()}",
                    category="test_execution_failed",
                    severity="high",
                    title="Execution failed",
                    details={"run_id": "run-1"},
                    project_id=project.id,
                    config=Settings(_env_file=None),
                )
                second = await create_alert(
                    db,
                    dedupe_key=first.dedupe_key,
                    category="test_execution_failed",
                    severity="high",
                    title="Execution failed",
                    details={"run_id": "run-1"},
                    project_id=project.id,
                    config=Settings(_env_file=None),
                )
                await db.commit()
                alert_id = first.id
                assert first.id == second.id

                listed = await list_alerts(project_id=project.id, status="open", limit=100, db=db)
                assert [alert.id for alert in listed] == [first.id]
                acknowledged = await acknowledge_alert(first.id, db)
                repeated = await acknowledge_alert(first.id, db)
                assert acknowledged.status == repeated.status == "acknowledged"
                audit_count = await db.scalar(
                    select(func.count()).select_from(AuditLog).where(
                        AuditLog.entity_type == "alert", AuditLog.entity_id == first.id
                    )
                )
                assert audit_count == 1
        finally:
            _principal_context.reset(token)
            if project_id:
                async with session_factory() as db:
                    if alert_id:
                        await db.execute(delete(AuditLog).where(AuditLog.entity_id == alert_id))
                    await db.execute(delete(Alert).where(Alert.project_id == project_id))
                    await db.execute(delete(Project).where(Project.id == project_id))
                    await db.commit()
            await engine.dispose()

    asyncio.run(scenario())
