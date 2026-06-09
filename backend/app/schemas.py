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
    locked: bool = False
    repository_status: str = "draft"
    repository_synced_at: Optional[datetime] = None
    steps: Optional[List[TestCaseStep]] = None

    class Config:
        orm_mode = True


class ApprovalAction(BaseModel):
    approved_by: Optional[str] = 'system'
    notes: Optional[str] = None


class FeedbackCreate(BaseModel):
    target_level: str
    target_id: uuid.UUID
    source: str
    feedback_type: str
    comment: str
    created_by: str


class FeedbackSummary(FeedbackCreate):
    id: uuid.UUID
    status: str = "open"
    resolved_at: Optional[datetime] = None
    resolution_notes: Optional[str] = None
    vector_id: Optional[str] = None
    created_at: datetime

    class Config:
        orm_mode = True


class FeedbackRevisionRequest(BaseModel):
    feedback_id: uuid.UUID
    action: Optional[str] = None
    created_by: str = "system"
    notes: Optional[str] = None


class RevisionRecordSummary(BaseModel):
    id: uuid.UUID
    feedback_id: Optional[uuid.UUID] = None
    target_level: str
    target_id: uuid.UUID
    action: str
    status: str
    created_by: str
    notes: Optional[str] = None
    source_snapshot: Optional[dict] = None
    result_snapshot: Optional[dict] = None
    created_at: datetime

    class Config:
        orm_mode = True


class QualityEvaluationSummary(BaseModel):
    id: uuid.UUID
    target_level: str
    target_id: uuid.UUID
    score: int
    status: str
    metrics: dict
    issues: List[dict]
    evaluated_by: str
    created_at: datetime

    class Config:
        orm_mode = True


class ApprovalRecordSummary(BaseModel):
    id: uuid.UUID
    target_level: str
    target_id: uuid.UUID
    approved_by: str
    approved_at: datetime
    version: int
    status: str
    notes: Optional[str] = None

    class Config:
        orm_mode = True


class AuditLogSummary(BaseModel):
    id: uuid.UUID
    entity_type: str
    entity_id: Optional[uuid.UUID] = None
    action: str
    actor: str
    details: Optional[dict] = None
    created_at: datetime

    class Config:
        orm_mode = True


class TestCaseVersionSummary(BaseModel):
    id: uuid.UUID
    test_case_id: uuid.UUID
    requirement_id: uuid.UUID
    scenario_id: uuid.UUID
    version: int
    title: str
    description: str
    prerequisite: Optional[str] = None
    priority: Optional[str] = None
    severity: Optional[str] = None
    category: Optional[str] = None
    type: Optional[str] = None
    status: str
    approved_by: str
    approved_at: datetime
    notes: Optional[str] = None
    steps_snapshot: List[dict]

    class Config:
        orm_mode = True


class ValidationIssue(BaseModel):
    field: str
    message: str
    severity: str = "error"


class ValidationResult(BaseModel):
    valid: bool
    target_level: str
    target_id: uuid.UUID
    issues: List[ValidationIssue]


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
