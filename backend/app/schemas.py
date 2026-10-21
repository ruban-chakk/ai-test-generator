import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TokenResponse(APIModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserSummary(APIModel):
    id: uuid.UUID
    username: str
    email: str
    role: str
    active: bool


class AuthConfiguration(APIModel):
    oidc_enabled: bool
    oidc_login_url: Optional[str] = None


class TestCaseStep(APIModel):
    step_number: int
    action: str
    expected_result: str



class TestCaseSummary(APIModel):
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



class ApprovalAction(APIModel):
    approved_by: Optional[str] = 'system'
    notes: Optional[str] = None


class FeedbackCreate(APIModel):
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



class FeedbackRevisionRequest(APIModel):
    feedback_id: uuid.UUID
    action: Optional[str] = None
    created_by: str = "system"
    notes: Optional[str] = None


class RevisionRecordSummary(APIModel):
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



class QualityEvaluationSummary(APIModel):
    id: uuid.UUID
    target_level: str
    target_id: uuid.UUID
    score: int
    status: str
    metrics: dict
    issues: List[dict]
    evaluated_by: str
    created_at: datetime



class ImpactAnalyzeRequest(APIModel):
    text: str
    project_id: Optional[uuid.UUID] = None
    context_ids: Optional[List[uuid.UUID]] = None
    created_by: str = "system"


class SemanticSearchResult(APIModel):
    vector_id: str
    entity_type: str
    entity_id: str
    title: str
    text: str
    score: float
    metadata: dict


class ImpactCandidate(APIModel):
    test_case_id: uuid.UUID
    requirement_id: uuid.UUID
    scenario_id: uuid.UUID
    title: str
    status: str
    repository_status: str
    similarity: float
    recommended_action: str
    reason: str
    priority: Optional[str] = None
    severity: Optional[str] = None
    category: Optional[str] = None
    type: Optional[str] = None


class ImpactAnalysisSummary(APIModel):
    id: uuid.UUID
    requirement_id: Optional[uuid.UUID] = None
    source_text: str
    similarity_threshold: float
    duplicates: List[ImpactCandidate]
    deprecations: List[ImpactCandidate]
    updates: List[ImpactCandidate]
    risk_score: int
    coverage_score: int
    summary: dict
    created_by: str
    created_at: datetime



class JiraImportRequest(APIModel):
    project_id: uuid.UUID
    jql: str
    max_results: int = Field(default=100, ge=1, le=1000)
    requested_by: str = "system"


class RepositorySyncRequest(APIModel):
    project_id: uuid.UUID
    repository: str
    branch: str = "main"
    requested_by: str = "system"


class IntegrationRunSummary(APIModel):
    id: uuid.UUID
    integration_type: str
    status: str
    requested_by: str
    parameters: dict
    result: dict
    started_at: datetime
    completed_at: Optional[datetime] = None



class RepositorySyncRunSummary(APIModel):
    id: uuid.UUID
    repository: str
    branch: str
    status: str
    synced_count: int
    vector_synced_count: int
    requested_by: str
    details: dict
    started_at: datetime
    completed_at: Optional[datetime] = None


class TestExecutionRequest(APIModel):
    project_id: uuid.UUID
    test_case_ids: List[uuid.UUID] = Field(min_length=1, max_length=100)
    environment: str = Field(default="default", min_length=1, max_length=100)
    request_id: uuid.UUID


class TestExecutionRunSummary(APIModel):
    id: uuid.UUID
    project_id: uuid.UUID
    test_case_id: uuid.UUID
    test_case_version: int
    environment: str
    runner: str
    status: str
    external_run_id: Optional[str] = None
    result: dict
    requested_by: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime



class CleanupRequest(APIModel):
    text: str


class CleanupResult(APIModel):
    original_text: str
    cleaned_text: str
    issues: List[dict]


class EvaluationRunRequest(APIModel):
    suite: str = "quality"
    requested_by: str = "system"


class EvaluationRunSummary(APIModel):
    id: uuid.UUID
    suite: str
    status: str
    score: int
    metrics: dict
    issues: List[dict]
    requested_by: str
    created_at: datetime



class MonitoringSummary(APIModel):
    status: str
    metrics: dict
    captured_at: datetime


class DependencyStatusSummary(APIModel):
    name: str
    status: str
    configured: bool


class DependencyHealthSummary(APIModel):
    status: str
    dependencies: List[DependencyStatusSummary]
    checked_at: datetime


class OutboxEventSummary(APIModel):
    id: uuid.UUID
    event_type: str
    aggregate_type: str
    aggregate_id: uuid.UUID
    status: str
    attempts: int
    available_at: datetime
    locked_at: Optional[datetime] = None
    locked_by: Optional[str] = None
    processed_at: Optional[datetime] = None
    last_error: Optional[str] = None
    created_at: datetime


class GovernancePolicyCreate(APIModel):
    name: str
    policy_type: str
    rules: dict
    created_by: str = "system"
    status: str = "active"


class GovernancePolicySummary(GovernancePolicyCreate):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime



class ApprovalRecordSummary(APIModel):
    id: uuid.UUID
    target_level: str
    target_id: uuid.UUID
    approved_by: str
    approved_at: datetime
    version: int
    status: str
    notes: Optional[str] = None



class AuditLogSummary(APIModel):
    id: uuid.UUID
    entity_type: str
    entity_id: Optional[uuid.UUID] = None
    action: str
    actor: str
    details: Optional[dict] = None
    created_at: datetime



class TestCaseVersionSummary(APIModel):
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



class ValidationIssue(APIModel):
    field: str
    message: str
    severity: str = "error"


class ValidationResult(APIModel):
    valid: bool
    target_level: str
    target_id: uuid.UUID
    issues: List[ValidationIssue]


class TestScenarioSummary(APIModel):
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



class TestScenarioCreate(APIModel):
    title: str
    description: str
    priority: Optional[str] = None
    severity: Optional[str] = None
    category: Optional[str] = None
    type: Optional[str] = None
    status: Optional[str] = 'draft'


class TestCaseCreate(APIModel):
    title: str
    description: str
    prerequisite: Optional[str] = None
    priority: Optional[str] = None
    severity: Optional[str] = None
    category: Optional[str] = None
    type: Optional[str] = None
    status: Optional[str] = 'draft'


class TestCaseStepCreate(APIModel):
    step_number: int
    action: str
    expected_result: str


class ProjectCreate(APIModel):
    name: str
    description: Optional[str] = None
    status: str = "active"


class ProjectSummary(ProjectCreate):
    id: uuid.UUID
    requirement_count: int = 0
    test_case_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ProjectMembershipUpsert(APIModel):
    user_id: uuid.UUID
    role: str = "reviewer"


class ProjectMembershipSummary(ProjectMembershipUpsert):
    id: uuid.UUID
    project_id: uuid.UUID
    username: str
    email: str
    created_at: datetime


class RequirementBase(APIModel):
    project_id: Optional[uuid.UUID] = None
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
