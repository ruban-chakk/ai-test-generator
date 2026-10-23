import asyncio
import os
import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes import create_semantic_calibration, list_semantic_calibrations
from app.core.security import Principal, _principal_context
from app.models import AuditLog, GovernancePolicy, Project, SemanticCalibrationRun
from app.schemas import SemanticCalibrationRequest, SemanticCalibrationSample


TEST_DSN = os.getenv("TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not TEST_DSN, reason="TEST_POSTGRES_DSN is not configured")


def test_calibration_is_idempotent_and_applies_project_policy() -> None:
    async def scenario() -> None:
        engine = create_async_engine(TEST_DSN)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        project_id: uuid.UUID | None = None
        token = _principal_context.set(
            Principal(user_id=uuid.uuid4(), username="calibration-admin", role="admin", token_version=1)
        )
        try:
            async with session_factory() as db:
                project = Project(name=f"calibration-{uuid.uuid4()}", status="active")
                db.add(project)
                await db.commit()
                await db.refresh(project)
                project_id = project.id
                samples = [
                    *(SemanticCalibrationSample(similarity=score, expected_action="duplicate") for score in (0.96, 0.91, 0.86)),
                    *(SemanticCalibrationSample(similarity=score, expected_action="update") for score in (0.74, 0.68, 0.57)),
                    *(SemanticCalibrationSample(similarity=score, expected_action="unrelated") for score in (0.41, 0.30, 0.20, 0.10)),
                ]
                payload = SemanticCalibrationRequest(project_id=project.id, samples=samples, apply=True)

                first = await create_semantic_calibration(payload, db)
                second = await create_semantic_calibration(payload, db)
                listed = await list_semantic_calibrations(project.id, db)

                assert first.id == second.id
                assert first.status == "applied"
                assert len(listed) == 1
                policy = await db.scalar(
                    select(GovernancePolicy).where(
                        GovernancePolicy.name == f"semantic-impact-thresholds:{project.id}"
                    )
                )
                assert policy is not None
                assert policy.rules["duplicate"] == first.proposed_thresholds["duplicate"]
                assert policy.rules["update"] == first.proposed_thresholds["update"]
        finally:
            _principal_context.reset(token)
            if project_id:
                async with session_factory() as db:
                    run_ids = select(SemanticCalibrationRun.id).where(
                        SemanticCalibrationRun.project_id == project_id
                    )
                    await db.execute(delete(AuditLog).where(AuditLog.entity_id.in_(run_ids)))
                    await db.execute(
                        delete(GovernancePolicy).where(
                            GovernancePolicy.name == f"semantic-impact-thresholds:{project_id}"
                        )
                    )
                    await db.execute(
                        delete(SemanticCalibrationRun).where(
                            SemanticCalibrationRun.project_id == project_id
                        )
                    )
                    await db.execute(delete(Project).where(Project.id == project_id))
                    await db.commit()
            await engine.dispose()

    asyncio.run(scenario())
