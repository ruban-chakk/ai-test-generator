import asyncio
import os
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.admin import put_model_configuration
from app.core.security import Principal, _principal_context
from app.models import (
    AIModelConfiguration,
    AuditLog,
    Organization,
    OrganizationMembership,
    Project,
    ProjectMembership,
    User,
)
from app.schemas import AIModelConfigurationUpdate


TEST_DSN = os.getenv("TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not TEST_DSN, reason="TEST_POSTGRES_DSN is not configured")


def configuration() -> AIModelConfigurationUpdate:
    return AIModelConfigurationUpdate(
        generation_model="generation-model",
        judge_model="judge-model",
        embedding_model="embedding-model",
        vector_provider="pinecone",
        vector_index="tenant-index",
        vector_namespace="tenant",
        evaluation_weights={"grounding": 1.0},
        pricing={"input_per_million": 1.0, "output_per_million": 2.0},
    )


def test_lower_level_admins_cannot_cross_scope_boundaries() -> None:
    async def scenario() -> None:
        engine = create_async_engine(TEST_DSN)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        ids: dict[str, uuid.UUID] = {}
        try:
            async with sessions() as db:
                organization = Organization(name=f"Tenant {uuid.uuid4()}", slug=f"tenant-{uuid.uuid4()}")
                project_admin = User(username=f"project-admin-{uuid.uuid4()}", email=f"project-{uuid.uuid4()}@example.com", role="user", password_hash="unused")
                org_admin = User(username=f"org-admin-{uuid.uuid4()}", email=f"org-{uuid.uuid4()}@example.com", role="user", password_hash="unused")
                db.add_all([organization, project_admin, org_admin])
                await db.flush()
                project = Project(organization_id=organization.id, name=f"Scoped project {uuid.uuid4()}", cost_center="CC-100")
                db.add(project)
                await db.flush()
                db.add_all([
                    ProjectMembership(project_id=project.id, user_id=project_admin.id, role="project_admin"),
                    OrganizationMembership(organization_id=organization.id, user_id=org_admin.id, role="org_admin"),
                ])
                await db.commit()
                ids.update(organization=organization.id, project=project.id, project_admin=project_admin.id, org_admin=org_admin.id)

            project_token = _principal_context.set(Principal(user_id=ids["project_admin"], username="project-admin", role="user", token_version=1))
            try:
                async with sessions() as db:
                    saved = await put_model_configuration("project", configuration(), ids["project"], db)
                    assert saved.scope_type == "project"
                async with sessions() as db:
                    with pytest.raises(HTTPException) as app_denied:
                        await put_model_configuration("app", configuration(), None, db)
                    assert app_denied.value.status_code == 403
                async with sessions() as db:
                    with pytest.raises(HTTPException) as org_denied:
                        await put_model_configuration("organization", configuration(), ids["organization"], db)
                    assert org_denied.value.status_code == 403
            finally:
                _principal_context.reset(project_token)

            org_token = _principal_context.set(Principal(user_id=ids["org_admin"], username="org-admin", role="user", token_version=1))
            try:
                async with sessions() as db:
                    saved = await put_model_configuration("organization", configuration(), ids["organization"], db)
                    assert saved.scope_type == "organization"
                async with sessions() as db:
                    with pytest.raises(HTTPException) as app_denied:
                        await put_model_configuration("app", configuration(), None, db)
                    assert app_denied.value.status_code == 403
            finally:
                _principal_context.reset(org_token)
        finally:
            async with sessions() as db:
                await db.execute(delete(AuditLog).where(AuditLog.entity_id.in_([ids.get("organization"), ids.get("project")])))
                await db.execute(delete(AIModelConfiguration).where(AIModelConfiguration.scope_id.in_([ids.get("organization"), ids.get("project")])))
                if ids.get("project"):
                    await db.execute(delete(ProjectMembership).where(ProjectMembership.project_id == ids["project"]))
                    await db.execute(delete(Project).where(Project.id == ids["project"]))
                if ids.get("organization"):
                    await db.execute(delete(OrganizationMembership).where(OrganizationMembership.organization_id == ids["organization"]))
                    await db.execute(delete(Organization).where(Organization.id == ids["organization"]))
                user_ids = [value for key, value in ids.items() if key in {"project_admin", "org_admin"}]
                if user_ids:
                    await db.execute(delete(User).where(User.id.in_(user_ids)))
                await db.commit()
            await engine.dispose()

    asyncio.run(scenario())
