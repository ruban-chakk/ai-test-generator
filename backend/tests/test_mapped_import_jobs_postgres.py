import asyncio
import json
import os
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.models import (
    AuditLog,
    ImportMappingProfile,
    IntegrationRun,
    MappedImportJob,
    OutboxEvent,
    Project,
    Requirement,
    RequirementVersion,
)
from app.services.mapped_import_jobs import MappedImportJobProcessor


TEST_DSN = os.getenv("TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not TEST_DSN, reason="TEST_POSTGRES_DSN is not configured")


def test_streamed_import_job_checkpoints_batches_and_completes_atomically() -> None:
    async def scenario() -> None:
        engine = create_async_engine(TEST_DSN)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        actor = f"mapped-job-{uuid.uuid4()}"
        project_id: uuid.UUID | None = None
        with tempfile.TemporaryDirectory() as spool:
            storage_key = f"{uuid.uuid4().hex}.json"
            source_path = Path(spool) / storage_key
            source_path.write_text(
                json.dumps([
                    {"key": "JOB-1", "summary": "First", "description": "First requirement"},
                    {"key": "JOB-2", "summary": "Second", "description": "Second requirement"},
                    {"key": "JOB-3", "summary": "Third", "description": "Third requirement"},
                ]),
                encoding="utf-8",
            )
            try:
                async with session_factory() as db:
                    project = Project(name=f"mapped-job-{uuid.uuid4()}", status="active")
                    db.add(project)
                    await db.flush()
                    project_id = project.id
                    configuration = {
                        "fields": {
                            "external_id": "key",
                            "title": "summary",
                            "description": "description",
                        },
                        "custom_fields": {},
                        "options": {"existing_record_strategy": "update"},
                    }
                    profile = ImportMappingProfile(
                        project_id=project.id,
                        name="Streamed requirements",
                        entity_type="requirement",
                        configuration=configuration,
                        version=1,
                        active=True,
                        created_by=actor,
                    )
                    db.add(profile)
                    await db.flush()
                    job = MappedImportJob(
                        project_id=project.id,
                        profile_id=profile.id,
                        profile_version=1,
                        entity_type="requirement",
                        mapping_snapshot=configuration,
                        original_filename="requirements.json",
                        storage_key=storage_key,
                        sha256="a" * 64,
                        byte_size=source_path.stat().st_size,
                        status="queued",
                        requested_by=actor,
                    )
                    db.add(job)
                    await db.commit()
                    job_id = job.id

                config = Settings(
                    _env_file=None,
                    mapped_import_spool_dir=spool,
                    mapped_job_batch_size=2,
                    mapped_job_max_records=100,
                )
                processor = MappedImportJobProcessor(session_factory, config=config, worker_id="job-worker")
                assert await processor.process_batch() == job_id
                async with session_factory() as db:
                    checkpoint = await db.get(MappedImportJob, job_id)
                    assert checkpoint is not None
                    assert checkpoint.status == "queued"
                    assert checkpoint.checkpoint_row == 2
                    assert checkpoint.created_record_count == 2
                    assert await db.scalar(
                        select(func.count()).select_from(Requirement).where(
                            Requirement.project_id == project_id
                        )
                    ) == 2

                assert await processor.process_batch() == job_id
                async with session_factory() as db:
                    completed = await db.get(MappedImportJob, job_id)
                    assert completed is not None
                    assert completed.status == "completed"
                    assert completed.checkpoint_row == 3
                    assert completed.created_record_count == 3
                    assert completed.completed_at is not None
                    assert await db.scalar(
                        select(func.count()).select_from(RequirementVersion).where(
                            RequirementVersion.project_id == project_id
                        )
                    ) == 3
                    assert await db.scalar(
                        select(func.count()).select_from(IntegrationRun).where(
                            IntegrationRun.requested_by == actor
                        )
                    ) == 1
                assert not source_path.exists()
            finally:
                if project_id:
                    async with session_factory() as db:
                        requirement_ids = select(Requirement.id).where(Requirement.project_id == project_id)
                        version_ids = select(RequirementVersion.id).where(
                            RequirementVersion.project_id == project_id
                        )
                        await db.execute(delete(OutboxEvent).where(OutboxEvent.aggregate_id.in_(version_ids)))
                        await db.execute(delete(AuditLog).where(AuditLog.actor == actor))
                        await db.execute(delete(IntegrationRun).where(IntegrationRun.requested_by == actor))
                        await db.execute(delete(RequirementVersion).where(RequirementVersion.project_id == project_id))
                        await db.execute(delete(Requirement).where(Requirement.project_id == project_id))
                        await db.execute(delete(MappedImportJob).where(MappedImportJob.project_id == project_id))
                        await db.execute(delete(ImportMappingProfile).where(ImportMappingProfile.project_id == project_id))
                        await db.execute(delete(Project).where(Project.id == project_id))
                        await db.commit()
        await engine.dispose()

    asyncio.run(scenario())
