import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class TestCaseStep(BaseModel):
    step_number: int
    action: str
    expected_result: str

    class Config:
        orm_mode = True


class TestCaseSummary(BaseModel):
    id: uuid.UUID
    title: str
    description: str
    prerequisite: Optional[str] = None
    priority: Optional[str] = None
    severity: Optional[str] = None
    category: Optional[str] = None
    type: Optional[str] = None
    status: str
    version: int
    approved_at: Optional[datetime] = None
    steps: Optional[List[TestCaseStep]] = None

    class Config:
        orm_mode = True


class TestScenarioSummary(BaseModel):
    id: uuid.UUID
    title: str
    description: str
    priority: Optional[str] = None
    severity: Optional[str] = None
    category: Optional[str] = None
    type: Optional[str] = None
    status: str
    version: int
    test_cases: Optional[List[TestCaseSummary]] = None

    class Config:
        orm_mode = True


class TestScenarioCreate(BaseModel):
    title: str
    description: str
    priority: Optional[str] = None
    severity: Optional[str] = None
    category: Optional[str] = None
    type: Optional[str] = None
    status: Optional[str] = 'draft'


class TestCaseCreate(BaseModel):
    title: str
    description: str
    prerequisite: Optional[str] = None
    priority: Optional[str] = None
    severity: Optional[str] = None
    category: Optional[str] = None
    type: Optional[str] = None
    status: Optional[str] = 'draft'


class TestCaseStepCreate(BaseModel):
    step_number: int
    action: str
    expected_result: str


class RequirementBase(BaseModel):
    external_id: Optional[str] = Field(None, description="External requirement ID")
    title: str
    description: str
    source: str


class RequirementCreate(RequirementBase):
    pass


class RequirementDetail(RequirementBase):
    id: uuid.UUID
    status: str = "draft"
    metadata_json: Optional[dict] = None
    scenarios: Optional[List[TestScenarioSummary]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        orm_mode = True
