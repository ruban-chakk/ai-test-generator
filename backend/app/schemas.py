import uuid
from datetime import datetime
from typing import Any, List, Literal, Optional

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
    external_id: Optional[str] = None
    source: str = "generated"
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
    custom_fields_json: dict = Field(default_factory=dict)
    custom_field_schema_json: dict = Field(default_factory=dict)


class ImportMappingProfileCreate(APIModel):
    project_id: uuid.UUID
    name: str = Field(min_length=1, max_length=255)
    entity_type: Literal["requirement", "test_case"]
    configuration: dict[str, Any]
    active: bool = True


class ImportMappingProfileUpdate(APIModel):
    name: str = Field(min_length=1, max_length=255)
    configuration: dict[str, Any]
    active: bool = True


class ImportMappingProfileSummary(ImportMappingProfileCreate):
    id: uuid.UUID
    version: int
    parent_profile_id: Optional[uuid.UUID] = None
    superseded_at: Optional[datetime] = None
    created_by: str
    created_at: datetime
    updated_at: datetime


class MappedImportPreview(APIModel):
    entity_type: Literal["requirement", "test_case"]
    source_record_count: int
    mapped_record_count: int
    valid_record_count: int
    skipped_record_count: int
    warning_count: int = 0
    error_count: int = 0
    issues: List[dict] = Field(default_factory=list)
    samples: List[dict] = Field(default_factory=list)


class MappedImportJobSummary(APIModel):
    id: uuid.UUID
    project_id: uuid.UUID
    profile_id: uuid.UUID
    profile_version: int
    entity_type: Literal["requirement", "test_case"]
    original_filename: str
    sha256: str
    byte_size: int
    status: Literal["queued", "processing", "completed", "failed", "cancelled"]
    checkpoint_row: int
    source_record_count: int
    mapped_record_count: int
    created_record_count: int
    updated_record_count: int
    existing_record_count: int
    skipped_record_count: int
    warning_count: int
    error_count: int
    result: dict = Field(default_factory=dict)
    last_error_type: Optional[str] = None
    requested_by: str
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None



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
    search_mode: Literal["semantic", "keyword", "hybrid"] = "semantic"
    semantic_score: Optional[float] = None
    keyword_score: Optional[float] = None
    matched_fields: List[str] = Field(default_factory=list)


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


class SemanticCalibrationSample(APIModel):
    similarity: float = Field(ge=0, le=1)
    expected_action: str


class SemanticCalibrationRequest(APIModel):
    project_id: uuid.UUID
    samples: List[SemanticCalibrationSample] = Field(min_length=10, max_length=5000)
    apply: bool = False


class SemanticCalibrationSummary(APIModel):
    id: uuid.UUID
    project_id: uuid.UUID
    dataset_digest: str
    sample_count: int
    label_distribution: dict
    previous_thresholds: dict
    proposed_thresholds: dict
    metrics: dict
    status: str
    requested_by: str
    created_at: datetime
    applied_at: Optional[datetime] = None



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


class AlertSummary(APIModel):
    id: uuid.UUID
    project_id: Optional[uuid.UUID] = None
    category: str
    severity: str
    title: str
    details: dict
    status: str
    delivery_status: str
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
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
    detail: Optional[str] = None


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


class ComplianceProfileUpdate(APIModel):
    frameworks: List[str] = Field(default_factory=list, max_length=10)
    evidence_retention_days: int = Field(default=365, ge=30, le=3650)
    evidence_export_enabled: bool = True
    pseudonymize_actors: bool = True
    approval_notes_required: bool = False


class ComplianceProfileSummary(ComplianceProfileUpdate):
    project_id: uuid.UUID
    updated_at: Optional[datetime] = None


class ComplianceEvidenceExport(APIModel):
    project_id: uuid.UUID
    generated_at: datetime
    period_start: datetime
    period_end: datetime
    profile: ComplianceProfileSummary
    evidence: dict
    record_counts: dict
    is_complete: bool
    truncated_sections: List[str] = Field(default_factory=list)
    sha256: str



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
    external_id: Optional[str] = None
    source: str = "generated"
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
    vector_id: Optional[str] = None
    custom_fields_json: dict = Field(default_factory=dict)



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
    external_id: Optional[str] = None
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
    version: int = 1
    metadata_json: Optional[dict] = None
    scenarios: Optional[List[TestScenarioSummary]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class RequirementVersionSummary(APIModel):
    id: uuid.UUID
    requirement_id: uuid.UUID
    project_id: Optional[uuid.UUID] = None
    version: int
    external_id: Optional[str] = None
    title: str
    description: str
    source: str
    status: str
    metadata_json: Optional[dict] = None
    vector_id: Optional[str] = None
    created_at: datetime
