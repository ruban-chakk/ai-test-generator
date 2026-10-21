import asyncio
import os
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes import (
    _create_approval_record,
    _pseudonymize_actor_fields,
    export_compliance_evidence,
    update_compliance_profile,
)
from app.core.security import Principal, _principal_context
from app.models import ApprovalRecord, AuditLog, GovernancePolicy, Project, Requirement
from app.schemas import ComplianceProfileUpdate


TEST_DSN = os.getenv("TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not TEST_DSN, reason="TEST_POSTGRES_DSN is not configured")


def test_nested_actor_fields_are_pseudonymized_without_changing_other_evidence() -> None:
    project_id = uuid.uuid4()
    result = _pseudonymize_actor_fields(
        {"requested_by": "alice", "nested": [{"approved_by": "bob", "status": "approved"}]},
        project_id,
    )
    assert result["requested_by"].startswith("actor-")
    assert result["nested"][0]["approved_by"].startswith("actor-")
    assert result["nested"][0]["status"] == "approved"


def test_project_compliance_profile_enforces_notes_and_exports_pseudonymized_evidence() -> None:
    async def scenario() -> None:
        engine = create_async_engine(TEST_DSN)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        project_id: uuid.UUID | None = None
        requirement_id: uuid.UUID | None = None
        token = _principal_context.set(
            Principal(user_id=uuid.uuid4(), username="compliance-admin", role="admin", token_version=1)
        )
        try:
            async with session_factory() as db:
                project = Project(name=f"compliance-{uuid.uuid4()}", status="active")
                db.add(project)
                await db.flush()
                requirement = Requirement(
                    project_id=project.id,
                    external_id="CMP-1",
                    title="Retain approval evidence",
                    description="The system retains approval evidence for audit review.",
                    source="manual",
                    status="approved",
                )
                db.add(requirement)
                await db.commit()
                project_id = project.id
                requirement_id = requirement.id

                profile = await update_compliance_profile(
                    project.id,
                    ComplianceProfileUpdate(
                        frameworks=["soc2", "ISO27001"],
                        evidence_retention_days=730,
                        evidence_export_enabled=True,
                        pseudonymize_actors=True,
                        approval_notes_required=True,
                    ),
                    db,
                )
                assert profile.frameworks == ["ISO27001", "SOC2"]

                with pytest.raises(HTTPException, match="requires approval notes"):
                    await _create_approval_record(
                        db, "requirement", requirement_id, "approved", 1, "compliance-admin"
                    )
                await db.rollback()
                await _create_approval_record(
                    db,
                    "requirement",
                    requirement_id,
                    "approved",
                    1,
                    "compliance-admin",
                    "Reviewed against control evidence.",
                )
                await db.commit()

                exported = await export_compliance_evidence(project_id, None, None, 1000, db)
                assert exported.profile.evidence_retention_days == 730
                assert exported.evidence["approvals"][0]["actor"].startswith("actor-")
                assert exported.evidence["approvals"][0]["notes"] == "Reviewed against control evidence."
                assert len(exported.sha256) == 64
                assert exported.record_counts["approvals"] == 1
                assert exported.is_complete is True
                assert exported.truncated_sections == []

                truncated = await export_compliance_evidence(project_id, None, None, 1, db)
                assert truncated.is_complete is False
                assert "audit_log" in truncated.truncated_sections
        finally:
            _principal_context.reset(token)
            if project_id:
                async with session_factory() as db:
                    if requirement_id:
                        await db.execute(delete(ApprovalRecord).where(ApprovalRecord.target_id == requirement_id))
                    await db.execute(delete(AuditLog).where(AuditLog.entity_id.in_([project_id, requirement_id])))
                    await db.execute(
                        delete(GovernancePolicy).where(
                            GovernancePolicy.name == f"compliance-profile:{project_id}"
                        )
                    )
                    await db.execute(delete(Requirement).where(Requirement.project_id == project_id))
                    await db.execute(delete(Project).where(Project.id == project_id))
                    await db.commit()
            await engine.dispose()

    asyncio.run(scenario())
