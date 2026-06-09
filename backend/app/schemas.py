from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class RequirementBase(BaseModel):
    external_id: Optional[str] = Field(None, description="External requirement ID")
    title: str
    description: str
    source: str


class RequirementCreate(RequirementBase):
    pass


class RequirementDetail(RequirementBase):
    id: str
    status: str = "draft"
    metadata: Optional[dict] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        orm_mode = True
