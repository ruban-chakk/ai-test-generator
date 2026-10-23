import asyncio
import os
import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes import (
    create_import_mapping_profile,
    list_import_mapping_profiles,
    rollback_import_mapping_profile,
    update_import_mapping_profile,
)
from app.core.security import Principal, _principal_context
from app.models import AuditLog, ImportMappingProfile, Project
from app.schemas import ImportMappingProfileCreate, ImportMappingProfileUpdate


TEST_DSN = os.getenv("TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not TEST_DSN, reason="TEST_POSTGRES_DSN is not configured")


def test_mapping_updates_create_immutable_revisions_and_support_rollback() -> None:
    async def scenario() -> None:
        engine = create_async_engine(TEST_DSN)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        project_id: uuid.UUID | None = None
        principal_token = _principal_context.set(
            Principal(user_id=uuid.uuid4(), username="mapping-admin", role="admin", token_version=1)
        )
        try:
            async with session_factory() as db:
                project = Project(name=f"mapping-revisions-{uuid.uuid4()}", status="active")
                db.add(project)
                await db.commit()
                await db.refresh(project)
                project_id = project.id
                base_config = {
                    "fields": {
                        "external_id": "key",
                        "title": "summary",
                        "description": "description",
                    },
                    "options": {"existing_record_strategy": "skip"},
                }
                first = await create_import_mapping_profile(
                    ImportMappingProfileCreate(
                        project_id=project.id,
                        name="Company stories",
                        entity_type="requirement",
                        configuration=base_config,
                    ),
                    db,
                )
                revised_config = {
                    **base_config,
                    "custom_fields": {
                        "owner": {"source": "owner", "type": "string", "required": True}
                    },
                }
                second = await update_import_mapping_profile(
                    first.id,
                    ImportMappingProfileUpdate(
                        name="Company stories",
                        configuration=revised_config,
                        active=True,
                    ),
                    db,
                )
                assert second.version == 2
                assert second.parent_profile_id == first.id
                active = await list_import_mapping_profiles(project.id, None, False, db)
                history = await list_import_mapping_profiles(project.id, None, True, db)
                assert [item.id for item in active] == [second.id]
                assert {item.version for item in history} == {1, 2}

                restored = await rollback_import_mapping_profile(first.id, db)
                assert restored.version == 3
                assert restored.configuration == base_config
                active = await list_import_mapping_profiles(project.id, None, False, db)
                assert [item.id for item in active] == [restored.id]
        finally:
            _principal_context.reset(principal_token)
            if project_id:
                async with session_factory() as db:
                    profile_ids = list(
                        (
                            await db.execute(
                                select(ImportMappingProfile.id).where(
                                    ImportMappingProfile.project_id == project_id
                                )
                            )
                        ).scalars().all()
                    )
                    if profile_ids:
                        await db.execute(delete(AuditLog).where(AuditLog.entity_id.in_(profile_ids)))
                    await db.execute(
                        delete(ImportMappingProfile).where(ImportMappingProfile.project_id == project_id)
                    )
                    await db.execute(delete(Project).where(Project.id == project_id))
                    await db.commit()
            await engine.dispose()

    asyncio.run(scenario())
