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
    settings_json: dict[str, Any] = Field(default_factory=dict)


class UserProfileUpdate(APIModel):
    username: str = Field(min_length=2, max_length=80)
    email: str = Field(min_length=3, max_length=320)


class UserSettingsUpdate(APIModel):
    theme: Literal["light", "dark", "system"] = "light"
    density: Literal["comfortable", "compact"] = "comfortable"
    reduce_motion: bool = False


class AdminUserCreate(APIModel):
    username: str = Field(min_length=2, max_length=80)
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=12, max_length=256)
    role: Literal["user", "reviewer", "tester", "test_lead", "product_manager", "approver", "app_admin"] = "user"


class AdminUserRoleUpdate(APIModel):
    role: Literal["user", "reviewer", "tester", "test_lead", "product_manager", "approver", "app_admin"]
    active: bool = True


class AdminContext(APIModel):
    is_app_admin: bool
    organization_admin_ids: List[uuid.UUID] = Field(default_factory=list)
    project_admin_ids: List[uuid.UUID] = Field(default_factory=list)


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


class TestCaseInventoryItem(TestCaseSummary):
    requirement_id: uuid.UUID
    requirement_title: str
    scenario_id: uuid.UUID
    scenario_title: str
    project_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


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
    status: Literal["queued", "processing", "paused", "completed", "failed", "cancelled"]
    checkpoint_row: int
    source_record_count: int
    mapped_record_count: int
    created_record_count: int
    updated_record_count: int
    existing_record_count: int
    skipped_record_count: int
    unresolved_record_count: int
    warning_count: int
    error_count: int
    result: dict = Field(default_factory=dict)
    last_error_type: Optional[str] = None
    requested_by: str
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None


class BulkOperationCreateRequest(APIModel):
    project_id: uuid.UUID
    operation_type: Literal["generate_test_cases", "impact_analysis"]
    requirement_ids: List[uuid.UUID] = Field(min_length=1, max_length=500)


class BulkOperationJobSummary(APIModel):
    id: uuid.UUID
    project_id: uuid.UUID
    operation_type: Literal["generate_test_cases", "impact_analysis"]
    status: Literal["queued", "processing", "paused", "completed", "failed", "cancelled"]
    requirement_ids: List[uuid.UUID] = Field(default_factory=list)
    total_count: int
    completed_count: int
    failed_count: int
    result: dict = Field(default_factory=dict)
    last_error_type: Optional[str] = None
    requested_by: str
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    cancel_requested: bool = False
    max_concurrency: int = 1


class UnresolvedImportRecordSummary(APIModel):
    id: uuid.UUID
    project_id: uuid.UUID
    profile_id: uuid.UUID
    import_job_id: Optional[uuid.UUID] = None
    entity_type: str
    external_id: str
    missing_reference: str
    status: str
    retry_count: int
    last_error_type: Optional[str] = None
    created_by: str
    created_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime] = None



class ApprovalAction(APIModel):
    approved_by: Optional[str] = 'system'
    notes: Optional[str] = None


class BulkApprovalRequest(APIModel):
    scope: Literal["requirement", "scenario", "test_case"]
    scenario_id: Optional[uuid.UUID] = None
    test_case_ids: List[uuid.UUID] = Field(default_factory=list, max_length=500)
    approved_by: Optional[str] = "system"
    notes: Optional[str] = None


class BulkApprovalItem(APIModel):
    test_case_id: uuid.UUID
    status: Literal["approved", "in_review", "blocked", "failed"]
    message: Optional[str] = None


class BulkApprovalResult(APIModel):
    scope: Literal["requirement", "scenario", "test_case"]
    requested_count: int
    processed_count: int
    approved_count: int
    in_review_count: int
    blocked_count: int
    failed_count: int
    items: List[BulkApprovalItem] = Field(default_factory=list)


class ApprovalStageDefinition(APIModel):
    name: str = Field(min_length=1, max_length=255)
    required_roles: List[str] = Field(min_length=1)
    minimum_approvals: int = Field(default=1, ge=1, le=20)


class ApprovalWorkflowUpdate(APIModel):
    name: str = Field(default="Generated test approval", min_length=1, max_length=255)
    stages: List[ApprovalStageDefinition] = Field(min_length=1, max_length=12)
    evaluation_required: bool = True
    minimum_evaluation_score: int = Field(default=80, ge=0, le=100)
    allow_same_approver_multiple_stages: bool = False


class ApprovalWorkflowSummary(ApprovalWorkflowUpdate):
    project_id: uuid.UUID
    version: int = 1
    updated_at: Optional[datetime] = None


class ApprovalWorkflowDecisionSummary(APIModel):
    id: uuid.UUID
    stage_index: int
    stage_name: str
    decision: str
    decided_by: str
    decided_role: str
    notes: Optional[str] = None
    created_at: datetime


class ApprovalWorkflowRunSummary(APIModel):
    id: uuid.UUID
    project_id: uuid.UUID
    test_case_id: uuid.UUID
    test_case_version: int
    content_sha256: str
    status: str
    current_stage: int
    policy: ApprovalWorkflowSummary
    quality_evaluation_id: Optional[uuid.UUID] = None
    decisions: List[ApprovalWorkflowDecisionSummary] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None


class KnowledgeDocumentCreate(APIModel):
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=500_000)
    source: str = Field(default="manual", min_length=1, max_length=64)


class KnowledgeDocumentSummary(KnowledgeDocumentCreate):
    id: uuid.UUID
    project_id: uuid.UUID
    status: str
    vector_id: Optional[str] = None
    created_by: str
    created_at: datetime
    updated_at: datetime


class FeedbackCreate(APIModel):
    target_level: str
    target_id: uuid.UUID
    source: str
    feedback_type: str
    comment: str
    created_by: str
    quality_evaluation_id: Optional[uuid.UUID] = None


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
    source_event_id: Optional[uuid.UUID] = None
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
    target_level: Literal["requirement", "scenario", "test_case"] = "requirement"
    target_id: Optional[uuid.UUID] = None
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


class SearchJudgmentCreate(APIModel):
    search_event_id: uuid.UUID
    entity_type: Literal["requirement", "test_case", "feedback"]
    entity_id: str = Field(min_length=1, max_length=255)
    rank: int = Field(ge=1, le=1000)
    judgment: Literal["clicked", "relevant", "not_relevant"]


class SearchJudgmentSummary(SearchJudgmentCreate):
    id: uuid.UUID
    created_by: str
    created_at: datetime


class SavedSearchCreate(APIModel):
    project_id: uuid.UUID
    name: str = Field(min_length=1, max_length=255)
    query: str = Field(min_length=2, max_length=500)
    mode: Literal["semantic", "keyword", "hybrid"] = "hybrid"
    entity_type: Optional[Literal["requirement", "test_case", "feedback"]] = None


class SavedSearchSummary(SavedSearchCreate):
    id: uuid.UUID
    created_by: str
    created_at: datetime
    updated_at: datetime


class SearchAnalyticsSummary(APIModel):
    project_id: uuid.UUID
    query_count: int
    zero_result_count: int
    fallback_count: int
    average_latency_ms: float
    judgments: dict[str, int] = Field(default_factory=dict)
    top_queries: List[dict] = Field(default_factory=list)


class CustomFieldFacetSummary(APIModel):
    field: str
    values: List[dict] = Field(default_factory=list)


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
    target_level: str = "requirement"
    target_id: Optional[uuid.UUID] = None
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


class IntegrationScheduleCreate(APIModel):
    project_id: uuid.UUID
    name: str = Field(min_length=1, max_length=255)
    integration_type: Literal["jira"] = "jira"
    configuration: dict[str, Any]
    interval_seconds: int = Field(default=3600, ge=300, le=2_592_000)
    enabled: bool = True


class IntegrationScheduleSummary(IntegrationScheduleCreate):
    id: uuid.UUID
    next_run_at: datetime
    last_run_at: Optional[datetime] = None
    last_status: Optional[str] = None
    last_error_type: Optional[str] = None
    created_by: str
    created_at: datetime
    updated_at: datetime



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


class TestCaseUpdate(APIModel):
    expected_version: int = Field(ge=1)
    title: str = Field(min_length=5, max_length=1000)
    description: str = Field(min_length=12, max_length=100_000)
    prerequisite: Optional[str] = Field(default=None, max_length=100_000)
    priority: Optional[str] = Field(default=None, max_length=100)
    severity: Optional[str] = Field(default=None, max_length=100)
    category: Optional[str] = Field(default=None, max_length=100)
    type: Optional[str] = Field(default=None, max_length=100)
    steps: List[TestCaseStep] = Field(min_length=1, max_length=500)


class TestCaseStepCreate(APIModel):
    step_number: int
    action: str
    expected_result: str


class ProjectCreate(APIModel):
    name: str
    description: Optional[str] = None
    status: str = "active"
    organization_id: Optional[uuid.UUID] = None
    cost_center: str = "unassigned"


class ProjectUpdate(APIModel):
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    status: Literal["active", "archived"] = "active"
    cost_center: Optional[str] = Field(default=None, min_length=1, max_length=128)


class ProjectSummary(ProjectCreate):
    id: uuid.UUID
    requirement_count: int = 0
    test_case_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class OrganizationCreate(APIModel):
    name: str = Field(min_length=2, max_length=255)
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,126}[a-z0-9]$")


class OrganizationSummary(OrganizationCreate):
    id: uuid.UUID
    status: str
    project_count: int = 0
    member_count: int = 0
    created_at: datetime


class OrganizationMembershipUpsert(APIModel):
    user_id: uuid.UUID
    role: Literal["org_admin", "member"] = "member"


class OrganizationMembershipSummary(OrganizationMembershipUpsert):
    id: uuid.UUID
    organization_id: uuid.UUID
    username: str
    email: str
    created_at: datetime


class InvitationCreate(APIModel):
    email: str = Field(min_length=3, max_length=320)
    organization_id: uuid.UUID
    project_id: Optional[uuid.UUID] = None
    organization_role: Literal["org_admin", "member"] = "member"
    project_role: Optional[str] = None
    expires_in_days: int = Field(default=7, ge=1, le=30)


class InvitationSummary(APIModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    project_id: Optional[uuid.UUID] = None
    email: str
    organization_role: str
    project_role: Optional[str] = None
    status: str
    expires_at: datetime
    created_at: datetime
    invitation_token: Optional[str] = None


class InvitationAccept(APIModel):
    username: str = Field(min_length=2, max_length=80)
    password: str = Field(min_length=12, max_length=256)


class AIModelConfigurationUpdate(APIModel):
    generation_model: str = Field(min_length=1, max_length=255)
    judge_model: str = Field(min_length=1, max_length=255)
    embedding_model: str = Field(min_length=1, max_length=255)
    vector_provider: Literal["pinecone"] = "pinecone"
    vector_index: str = Field(min_length=1, max_length=255)
    vector_namespace: str = Field(min_length=1, max_length=255)
    vector_host: Optional[str] = Field(default=None, max_length=500)
    credential_reference: Optional[str] = Field(default=None, max_length=255)
    evaluation_weights: dict[str, float] = Field(default_factory=dict)
    pricing: dict[str, float] = Field(default_factory=dict)


class AIModelConfigurationSummary(AIModelConfigurationUpdate):
    id: uuid.UUID
    scope_type: str
    scope_id: Optional[uuid.UUID] = None
    updated_by: uuid.UUID
    updated_at: datetime


class PromptConfigurationUpdate(APIModel):
    prompt_key: Literal["test_case_generation", "feedback_regeneration", "test_case_evaluation"]
    system_template: str = Field(min_length=1, max_length=50000)
    user_template: str = Field(min_length=1, max_length=50000)
    variables: list[str] = Field(default_factory=list, max_length=100)
    temperature: Optional[float] = Field(default=None, ge=0, le=2)
    change_notes: Optional[str] = Field(default=None, max_length=2000)
    status: Literal["draft", "published", "retired"] = "published"


class PromptConfigurationSummary(PromptConfigurationUpdate):
    id: uuid.UUID
    scope_type: str
    scope_id: Optional[uuid.UUID] = None
    version: int
    content_checksum: str
    parent_configuration_id: Optional[uuid.UUID] = None
    parent_version: Optional[int] = None
    created_by: uuid.UUID
    approved_by: Optional[uuid.UUID] = None
    published_at: Optional[datetime] = None
    updated_by: uuid.UUID
    created_at: datetime
    updated_at: datetime


class PromptConfigurationVersionSummary(APIModel):
    id: uuid.UUID
    prompt_configuration_id: uuid.UUID
    prompt_key: Literal["test_case_generation", "feedback_regeneration", "test_case_evaluation"]
    scope_type: str
    scope_id: Optional[uuid.UUID] = None
    version: int
    system_template: str
    user_template: str
    variables: list[str]
    temperature: Optional[float] = None
    change_notes: Optional[str] = None
    status: str
    content_checksum: str
    parent_configuration_id: Optional[uuid.UUID] = None
    parent_version: Optional[int] = None
    created_by: uuid.UUID
    approved_by: Optional[uuid.UUID] = None
    published_at: Optional[datetime] = None
    created_at: datetime


class EffectivePromptConfigurationSummary(PromptConfigurationSummary):
    effective_scope_type: str
    effective_scope_id: Optional[uuid.UUID] = None
    inherited: bool = False


class AICostSummary(APIModel):
    scope_type: str
    scope_id: uuid.UUID
    total_cost_micros: int
    total_input_tokens: int
    total_output_tokens: int
    by_project: List[dict] = Field(default_factory=list)
    by_model: List[dict] = Field(default_factory=list)
    unpriced_models: List[str] = Field(default_factory=list)


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
