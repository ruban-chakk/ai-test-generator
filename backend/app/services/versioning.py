from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Requirement, RequirementVersion


async def snapshot_requirement(
    db: AsyncSession,
    requirement: Requirement,
) -> RequirementVersion:
    vector_id = f"requirement:{requirement.id}:v{requirement.version}"
    version = RequirementVersion(
        requirement_id=requirement.id,
        project_id=requirement.project_id,
        version=requirement.version,
        external_id=requirement.external_id,
        title=requirement.title,
        description=requirement.description,
        source=requirement.source,
        status=requirement.status,
        metadata_json=requirement.metadata_json,
        vector_id=vector_id,
    )
    requirement.vector_id = vector_id
    db.add(version)
    await db.flush()
    return version
