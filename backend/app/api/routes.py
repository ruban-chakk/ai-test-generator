from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db import get_db
from app.models import Requirement
from app.schemas import RequirementCreate, RequirementDetail

api_router = APIRouter()


@api_router.get("/requirements", response_model=list[RequirementDetail], tags=["Requirements"])
async def list_requirements(db: AsyncSession = Depends(get_db)) -> list[RequirementDetail]:
    result = await db.execute(select(Requirement).order_by(Requirement.updated_at.desc()))
    requirements = result.scalars().all()
    return requirements


@api_router.post("/requirements", response_model=RequirementDetail, tags=["Requirements"])
async def create_requirement(
    payload: RequirementCreate,
    db: AsyncSession = Depends(get_db),
) -> RequirementDetail:
    requirement = Requirement(
        external_id=payload.external_id,
        title=payload.title,
        description=payload.description,
        source=payload.source,
        status="draft",
    )
    db.add(requirement)
    await db.commit()
    await db.refresh(requirement)
    return requirement


@api_router.get("/requirements/{requirement_id}", response_model=RequirementDetail, tags=["Requirements"])
async def get_requirement(requirement_id: str, db: AsyncSession = Depends(get_db)) -> RequirementDetail:
    result = await db.execute(select(Requirement).where(Requirement.id == requirement_id))
    requirement = result.scalars().first()
    if not requirement:
        raise HTTPException(status_code=404, detail="Requirement not found")
    return requirement
