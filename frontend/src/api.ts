export type TestCaseStep = {
  step_number: number;
  action: string;
  expected_result: string;
};

declare global {
  interface ImportMetaEnv {
    readonly VITE_API_BASE_URL?: string;
  }

  interface ImportMeta {
    readonly env: ImportMetaEnv;
  }
}

export {};

export type TestCaseSummary = {
  id: string;
  external_id?: string;
  source?: string;
  title: string;
  description: string;
  prerequisite?: string;
  priority?: string;
  severity?: string;
  category?: string;
  type?: string;
  status: string;
  version: number;
  approved_at?: string;
  locked: boolean;
  repository_status: string;
  repository_synced_at?: string;
  steps?: TestCaseStep[];
  custom_fields_json?: Record<string, unknown>;
  custom_field_schema_json?: Record<string, unknown>;
};

export type TestCaseInventoryItem = TestCaseSummary & {
  requirement_id: string;
  requirement_title: string;
  scenario_id: string;
  scenario_title: string;
  project_id: string;
  created_at: string;
  updated_at: string;
};

export type TestScenarioSummary = {
  id: string;
  external_id?: string;
  title: string;
  description: string;
  priority?: string;
  severity?: string;
  category?: string;
  type?: string;
  status: string;
  version: number;
  test_cases?: TestCaseSummary[];
};

export type ProjectSummary = {
  id: string;
  organization_id?: string;
  name: string;
  description?: string;
  cost_center?: string;
  status: string;
  requirement_count: number;
  test_case_count: number;
  created_at?: string;
  updated_at?: string;
};

export type BulkOperationType = 'generate_test_cases' | 'impact_analysis';

export type BulkOperationItem = {
  requirement_id: string;
  status: 'queued' | 'processing' | 'completed' | 'failed' | 'cancelled';
  message?: string | null;
};

export type BulkOperationJob = {
  id: string;
  project_id: string;
  operation_type: BulkOperationType;
  status: 'queued' | 'processing' | 'paused' | 'completed' | 'failed' | 'cancelled';
  requirement_ids: string[];
  total_count: number;
  completed_count: number;
  failed_count: number;
  result: { items?: BulkOperationItem[] };
  last_error_type?: string | null;
  requested_by: string;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
  cancel_requested?: boolean;
  max_concurrency?: number;
};

export type ProjectCreatePayload = {
  name: string;
  description?: string;
  status?: string;
  organization_id?: string;
  cost_center?: string;
};

export type AdminContext = {
  is_app_admin: boolean;
  organization_admin_ids: string[];
  project_admin_ids: string[];
};

export type OrganizationSummary = {
  id: string;
  name: string;
  slug: string;
  status: string;
  project_count: number;
  member_count: number;
  created_at: string;
};

export type InvitationSummary = {
  id: string;
  organization_id: string;
  project_id?: string;
  email: string;
  organization_role: string;
  project_role?: string;
  status: string;
  expires_at: string;
  created_at: string;
  invitation_token?: string;
};

export type ScopedMembership = {
  id: string;
  organization_id?: string;
  project_id?: string;
  user_id: string;
  username: string;
  email: string;
  role: string;
  created_at: string;
};

export type AIModelConfiguration = {
  id?: string;
  scope_type?: string;
  scope_id?: string;
  generation_model: string;
  judge_model: string;
  embedding_model: string;
  vector_provider: 'pinecone';
  vector_index: string;
  vector_namespace: string;
  vector_host?: string;
  credential_reference?: string;
  evaluation_weights: Record<string, number>;
  pricing: Record<string, unknown>;
  updated_by?: string;
  updated_at?: string;
};

export type PromptConfiguration = {
  id?: string;
  scope_type?: string;
  scope_id?: string;
  prompt_key: 'test_case_generation' | 'feedback_regeneration' | 'test_case_evaluation';
  system_template: string;
  user_template: string;
  variables: string[];
  temperature?: number;
  change_notes?: string;
  version?: number;
  status?: 'draft' | 'published' | 'retired';
  content_checksum?: string;
  parent_configuration_id?: string;
  parent_version?: number;
  created_by?: string;
  approved_by?: string;
  published_at?: string;
  updated_by?: string;
  created_at?: string;
  updated_at?: string;
  effective_scope_type?: string;
  effective_scope_id?: string;
  inherited?: boolean;
};

export type PromptConfigurationVersion = Omit<PromptConfiguration, 'id' | 'updated_at'> & {
  id: string;
  prompt_configuration_id: string;
  created_at: string;
  content_checksum: string;
  change_notes?: string;
};

export type AICostSummary = {
  scope_type: string;
  scope_id: string;
  total_cost_micros: number;
  total_input_tokens: number;
  total_output_tokens: number;
  by_project: { project_id: string; cost_micros: number; tokens: number }[];
  by_model: { model: string; cost_micros: number; input_tokens: number; output_tokens: number; tokens: number; pricing_sources: string[] }[];
  unpriced_models: string[];
};

export type UserPreferences = {
  theme: 'light' | 'dark' | 'system';
  density: 'comfortable' | 'compact';
  reduce_motion: boolean;
};

export type RequirementSummary = {
  id: string;
  project_id?: string;
  external_id?: string;
  title: string;
  description?: string;
  source: string;
  status: string;
  version?: number;
  metadata_json?: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
};

export type RequirementVersionSummary = {
  id: string;
  requirement_id: string;
  project_id?: string;
  version: number;
  external_id?: string;
  title: string;
  description: string;
  source: string;
  status: string;
  metadata_json?: Record<string, unknown>;
  vector_id?: string;
  created_at: string;
};

export type RequirementDetail = RequirementSummary & {
  scenarios?: TestScenarioSummary[];
};

export type RequirementCreatePayload = {
  project_id?: string;
  external_id?: string;
  title: string;
  description: string;
  source: string;
};

export type TestScenarioCreatePayload = {
  title: string;
  description: string;
  priority?: string;
  severity?: string;
  category?: string;
  type?: string;
  status?: string;
};

export type TestCaseCreatePayload = {
  title: string;
  description: string;
  prerequisite?: string;
  priority?: string;
  severity?: string;
  category?: string;
  type?: string;
  status?: string;
};

export type TestCaseUpdatePayload = Omit<TestCaseCreatePayload, 'status'> & {
  expected_version: number;
  steps: TestCaseStep[];
};

export type TestCaseStepCreatePayload = {
  step_number: number;
  action: string;
  expected_result: string;
};

export type ApprovalActionPayload = {
  approved_by?: string;
  notes?: string;
};

export type BulkApprovalResult = {
  scope: 'requirement' | 'scenario' | 'test_case';
  requested_count: number;
  processed_count: number;
  approved_count: number;
  in_review_count: number;
  blocked_count: number;
  failed_count: number;
  items: { test_case_id: string; status: 'approved' | 'in_review' | 'blocked' | 'failed'; message?: string }[];
};

export type ApprovalStageDefinition = {
  name: string;
  required_roles: string[];
  minimum_approvals: number;
};

export type ApprovalWorkflow = {
  project_id: string;
  name: string;
  version: number;
  stages: ApprovalStageDefinition[];
  evaluation_required: boolean;
  minimum_evaluation_score: number;
  allow_same_approver_multiple_stages: boolean;
  updated_at?: string;
};

export type ApprovalWorkflowDecision = {
  id: string;
  stage_index: number;
  stage_name: string;
  decision: string;
  decided_by: string;
  decided_role: string;
  notes?: string;
  created_at: string;
};

export type ApprovalWorkflowRun = {
  id: string;
  project_id: string;
  test_case_id: string;
  test_case_version: number;
  content_sha256: string;
  status: string;
  current_stage: number;
  policy: ApprovalWorkflow;
  quality_evaluation_id?: string;
  decisions: ApprovalWorkflowDecision[];
  created_at: string;
  updated_at: string;
  completed_at?: string;
};

export type KnowledgeDocument = {
  id: string;
  project_id: string;
  title: string;
  content: string;
  source: string;
  status: string;
  vector_id?: string;
  created_by: string;
  created_at: string;
  updated_at: string;
};

export type FeedbackCreatePayload = {
  target_level: string;
  target_id: string;
  source: string;
  feedback_type: string;
  comment: string;
  created_by: string;
  quality_evaluation_id?: string;
};

export type FeedbackSummary = FeedbackCreatePayload & {
  id: string;
  status: string;
  resolved_at?: string;
  resolution_notes?: string;
  vector_id?: string;
  created_at: string;
};

export type FeedbackRevisionPayload = {
  feedback_id: string;
  action?: string;
  created_by: string;
  notes?: string;
};

export type RevisionRecordSummary = {
  id: string;
  feedback_id?: string;
  target_level: string;
  target_id: string;
  action: string;
  status: string;
  created_by: string;
  notes?: string;
  source_snapshot?: Record<string, unknown>;
  result_snapshot?: Record<string, unknown>;
  created_at: string;
};

export type QualityEvaluationSummary = {
  id: string;
  source_event_id?: string;
  target_level: string;
  target_id: string;
  score: number;
  status: string;
  metrics: Record<string, unknown>;
  issues: Record<string, unknown>[];
  evaluated_by: string;
  created_at: string;
};

export type ImpactCandidate = {
  test_case_id: string;
  requirement_id: string;
  scenario_id: string;
  title: string;
  status: string;
  repository_status: string;
  similarity: number;
  recommended_action: string;
  reason: string;
  priority?: string;
  severity?: string;
  category?: string;
  type?: string;
};

export type ImpactAnalysisSummary = {
  id: string;
  target_level: 'requirement' | 'scenario' | 'test_case';
  target_id?: string;
  requirement_id?: string;
  source_text: string;
  similarity_threshold: number;
  duplicates: ImpactCandidate[];
  deprecations: ImpactCandidate[];
  updates: ImpactCandidate[];
  risk_score: number;
  coverage_score: number;
  summary: Record<string, unknown>;
  created_by: string;
  created_at: string;
};

export type ImpactAnalyzePayload = {
  text: string;
  project_id?: string;
  context_ids?: string[];
  created_by: string;
};

export type SemanticCalibrationSample = {
  similarity: number;
  expected_action: 'duplicate' | 'update' | 'unrelated';
};

export type SemanticCalibrationSummary = {
  id: string;
  project_id: string;
  dataset_digest: string;
  sample_count: number;
  label_distribution: Record<string, number>;
  previous_thresholds: Record<string, number>;
  proposed_thresholds: Record<string, number>;
  metrics: { accuracy: number; macro_f1: number; confusion: Record<string, Record<string, number>> };
  status: 'proposed' | 'applied';
  requested_by: string;
  created_at: string;
  applied_at?: string;
};

export type ComplianceProfile = {
  project_id: string;
  frameworks: string[];
  evidence_retention_days: number;
  evidence_export_enabled: boolean;
  pseudonymize_actors: boolean;
  approval_notes_required: boolean;
  updated_at?: string;
};

export type ComplianceEvidenceExport = {
  project_id: string;
  generated_at: string;
  period_start: string;
  period_end: string;
  profile: ComplianceProfile;
  evidence: Record<string, unknown>;
  record_counts: Record<string, number>;
  is_complete: boolean;
  truncated_sections: string[];
  sha256: string;
};

export type SemanticSearchResult = {
  vector_id: string;
  entity_type: 'requirement' | 'test_case' | 'feedback';
  entity_id: string;
  title: string;
  text: string;
  score: number;
  metadata: Record<string, unknown>;
  search_mode: SearchMode;
  semantic_score?: number;
  keyword_score?: number;
  matched_fields: string[];
};

export type SearchMode = 'hybrid' | 'semantic' | 'keyword';
export type TestCaseApprovalFilter = 'all' | 'approved' | 'unapproved';

export async function searchArtifacts(
  projectId: string,
  query: string,
  mode: SearchMode,
  entityType?: SemanticSearchResult['entity_type'],
  offset = 0,
  customField?: string,
  customValue?: string,
  testCaseApproval: TestCaseApprovalFilter = 'all',
): Promise<SemanticSearchResult[]> {
  const params = new URLSearchParams({ project_id: projectId, query, mode });
  if (entityType) params.set('entity_type', entityType);
  if (offset) params.set('offset', String(offset));
  if (customField && customValue !== undefined) {
    params.set('custom_field', customField);
    params.set('custom_value', customValue);
  }
  if (testCaseApproval !== 'all') params.set('test_case_approval', testCaseApproval);
  return request<SemanticSearchResult[]>(`${API_BASE_URL}/search?${params.toString()}`, {
    headers: { 'Content-Type': 'application/json' },
  });
}

export type SavedSearch = {
  id: string;
  project_id: string;
  name: string;
  query: string;
  mode: SearchMode;
  entity_type?: SemanticSearchResult['entity_type'];
  created_by: string;
  created_at: string;
  updated_at: string;
};

export async function getSavedSearches(projectId: string): Promise<SavedSearch[]> {
  const params = new URLSearchParams({ project_id: projectId });
  return request<SavedSearch[]>(`${API_BASE_URL}/search/saved?${params.toString()}`);
}

export async function saveArtifactSearch(payload: {
  project_id: string;
  name: string;
  query: string;
  mode: SearchMode;
  entity_type?: SemanticSearchResult['entity_type'];
}): Promise<SavedSearch> {
  return request<SavedSearch>(`${API_BASE_URL}/search/saved`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function recordSearchJudgment(payload: {
  search_event_id: string;
  entity_type: SemanticSearchResult['entity_type'];
  entity_id: string;
  rank: number;
  judgment: 'clicked' | 'relevant' | 'not_relevant';
}): Promise<void> {
  await request(`${API_BASE_URL}/search/judgments`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export type IntegrationRunSummary = {
  id: string;
  integration_type: string;
  status: string;
  requested_by: string;
  parameters: Record<string, unknown>;
  result: Record<string, unknown>;
  started_at: string;
  completed_at?: string;
};

export type IntegrationSchedule = {
  id: string;
  project_id: string;
  name: string;
  integration_type: 'jira';
  configuration: Record<string, unknown>;
  interval_seconds: number;
  enabled: boolean;
  next_run_at: string;
  last_run_at?: string;
  last_status?: string;
  last_error_type?: string;
  created_by: string;
  created_at: string;
  updated_at: string;
};

export type ImportMappingProfile = {
  id: string;
  project_id: string;
  name: string;
  entity_type: 'requirement' | 'test_case';
  configuration: Record<string, unknown>;
  version: number;
  parent_profile_id?: string;
  active: boolean;
  superseded_at?: string;
  created_by: string;
  created_at: string;
  updated_at: string;
};

export type MappedImportPreview = {
  entity_type: 'requirement' | 'test_case';
  source_record_count: number;
  mapped_record_count: number;
  valid_record_count: number;
  skipped_record_count: number;
  warning_count: number;
  error_count: number;
  issues: Array<Record<string, unknown>>;
  samples: Array<Record<string, unknown>>;
};

export type UnresolvedImportRecord = {
  id: string;
  project_id: string;
  profile_id: string;
  import_job_id?: string;
  entity_type: string;
  external_id: string;
  missing_reference: string;
  status: 'pending' | 'resolved' | 'dismissed';
  retry_count: number;
  last_error_type?: string;
  created_by: string;
  created_at: string;
  updated_at: string;
  resolved_at?: string;
};

export type MappedImportJob = {
  id: string;
  project_id: string;
  profile_id: string;
  profile_version: number;
  entity_type: 'requirement' | 'test_case';
  original_filename: string;
  sha256: string;
  byte_size: number;
  status: 'queued' | 'processing' | 'completed' | 'failed' | 'cancelled';
  checkpoint_row: number;
  source_record_count: number;
  mapped_record_count: number;
  created_record_count: number;
  updated_record_count: number;
  existing_record_count: number;
  skipped_record_count: number;
  unresolved_record_count: number;
  warning_count: number;
  error_count: number;
  result: Record<string, unknown>;
  last_error_type?: string;
  requested_by: string;
  created_at: string;
  updated_at: string;
  completed_at?: string;
};

export type RepositorySyncRunSummary = {
  id: string;
  repository: string;
  branch: string;
  status: string;
  synced_count: number;
  vector_synced_count: number;
  requested_by: string;
  details: Record<string, unknown>;
  started_at: string;
  completed_at?: string;
};

export type TestExecutionRunSummary = {
  id: string;
  project_id: string;
  test_case_id: string;
  test_case_version: number;
  environment: string;
  runner: string;
  status: 'queued' | 'running' | 'passed' | 'failed' | 'error' | 'cancelled';
  external_run_id?: string;
  result: Record<string, unknown>;
  requested_by: string;
  started_at?: string;
  completed_at?: string;
  created_at: string;
};

export type CleanupResult = {
  original_text: string;
  cleaned_text: string;
  issues: Record<string, unknown>[];
};

export type EvaluationRunSummary = {
  id: string;
  suite: string;
  status: string;
  score: number;
  metrics: Record<string, unknown>;
  issues: Record<string, unknown>[];
  requested_by: string;
  created_at: string;
};

export type MonitoringSummary = {
  status: string;
  metrics: Record<string, number>;
  captured_at: string;
};

export type DependencyStatusSummary = {
  name: string;
  status: 'healthy' | 'unhealthy' | 'unreachable' | 'misconfigured' | 'not_configured';
  configured: boolean;
  detail?: string;
};

export type DependencyHealthSummary = {
  status: 'healthy' | 'degraded';
  dependencies: DependencyStatusSummary[];
  checked_at: string;
};

export type OutboxEventSummary = {
  id: string;
  event_type: string;
  aggregate_type: string;
  aggregate_id: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  attempts: number;
  available_at: string;
  locked_at?: string;
  locked_by?: string;
  processed_at?: string;
  last_error?: string;
  created_at: string;
};

export type AlertSummary = {
  id: string;
  project_id?: string;
  category: string;
  severity: string;
  title: string;
  details: Record<string, unknown>;
  status: 'open' | 'acknowledged';
  delivery_status: 'not_configured' | 'pending' | 'delivered' | 'failed';
  acknowledged_by?: string;
  acknowledged_at?: string;
  delivered_at?: string;
  created_at: string;
};

export type GovernancePolicySummary = {
  id: string;
  name: string;
  policy_type: string;
  rules: Record<string, unknown>;
  created_by: string;
  status: string;
  created_at: string;
  updated_at: string;
};

export type ApprovalRecordSummary = {
  id: string;
  target_level: string;
  target_id: string;
  approved_by: string;
  approved_at: string;
  version: number;
  status: string;
  notes?: string;
};

export type TestCaseVersionSummary = {
  id: string;
  test_case_id: string;
  requirement_id: string;
  scenario_id: string;
  version: number;
  external_id?: string;
  source?: string;
  title: string;
  description: string;
  prerequisite?: string;
  priority?: string;
  severity?: string;
  category?: string;
  type?: string;
  status: string;
  approved_by: string;
  approved_at: string;
  notes?: string;
  steps_snapshot: Record<string, unknown>[];
  vector_id?: string;
};

export type AuditLogSummary = {
  id: string;
  entity_type: string;
  entity_id?: string;
  action: string;
  actor: string;
  details?: Record<string, unknown>;
  created_at: string;
};

export type ValidationIssue = {
  field: string;
  message: string;
  severity: string;
};

export type ValidationResult = {
  valid: boolean;
  target_level: string;
  target_id: string;
  issues: ValidationIssue[];
};

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';
const browserFetch = globalThis.fetch.bind(globalThis);

async function fetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  return browserFetch(input, { ...init, credentials: 'include' });
}

export type AuthenticatedUser = {
  id: string;
  username: string;
  email: string;
  role: 'user' | 'reviewer' | 'tester' | 'test_lead' | 'product_manager' | 'approver' | 'admin' | 'app_admin';
  active: boolean;
  settings_json?: Partial<UserPreferences>;
};

export type AuthConfiguration = {
  oidc_enabled: boolean;
  oidc_login_url?: string;
};

export async function getAuthConfiguration(): Promise<AuthConfiguration> {
  return request<AuthConfiguration>(`${API_BASE_URL}/auth/config`);
}

export async function login(username: string, password: string): Promise<AuthenticatedUser> {
  const body = new URLSearchParams({ username, password });
  const response = await fetch(`${API_BASE_URL}/auth/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  });
  await handleResponse<{ access_token: string }>(response);
  return getCurrentUser();
}

export async function acceptInvitation(token: string, payload: { username: string; password: string }): Promise<AuthenticatedUser> {
  return request<AuthenticatedUser>(`${API_BASE_URL}/auth/invitations/${encodeURIComponent(token)}/accept`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  });
}

export async function getCurrentUser(): Promise<AuthenticatedUser> {
  return request<AuthenticatedUser>(`${API_BASE_URL}/auth/me`);
}

export async function updateCurrentUser(payload: { username: string; email: string }): Promise<AuthenticatedUser> {
  return request<AuthenticatedUser>(`${API_BASE_URL}/auth/me`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function updateUserSettings(payload: UserPreferences): Promise<AuthenticatedUser> {
  return request<AuthenticatedUser>(`${API_BASE_URL}/auth/me/settings`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function getAdminContext(): Promise<AdminContext> {
  return request<AdminContext>(`${API_BASE_URL}/admin/context`);
}

export async function getOrganizations(): Promise<OrganizationSummary[]> {
  return request<OrganizationSummary[]>(`${API_BASE_URL}/admin/organizations`);
}

export async function createOrganization(payload: { name: string; slug: string }): Promise<OrganizationSummary> {
  return request<OrganizationSummary>(`${API_BASE_URL}/admin/organizations`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  });
}

export async function getAdminUsers(organizationId?: string, projectId?: string): Promise<AuthenticatedUser[]> {
  const params = new URLSearchParams();
  if (organizationId) params.set('organization_id', organizationId);
  if (projectId) params.set('project_id', projectId);
  return request<AuthenticatedUser[]>(`${API_BASE_URL}/admin/users${params.size ? `?${params}` : ''}`);
}

export async function createAdminUser(payload: { username: string; email: string; password: string; role: AuthenticatedUser['role'] }): Promise<AuthenticatedUser> {
  return request<AuthenticatedUser>(`${API_BASE_URL}/admin/users`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  });
}

export async function updateAdminUserRole(userId: string, payload: { role: AuthenticatedUser['role']; active: boolean }): Promise<AuthenticatedUser> {
  return request<AuthenticatedUser>(`${API_BASE_URL}/admin/users/${userId}/role`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  });
}

export async function createInvitation(payload: { email: string; organization_id: string; project_id?: string; organization_role: string; project_role?: string; expires_in_days: number }): Promise<InvitationSummary> {
  return request<InvitationSummary>(`${API_BASE_URL}/admin/invitations`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  });
}

export async function getOrganizationMembers(organizationId: string): Promise<ScopedMembership[]> {
  return request<ScopedMembership[]>(`${API_BASE_URL}/admin/organizations/${organizationId}/members`);
}

export async function putOrganizationMember(organizationId: string, userId: string, role: string): Promise<ScopedMembership> {
  return request<ScopedMembership>(`${API_BASE_URL}/admin/organizations/${organizationId}/members`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ user_id: userId, role }),
  });
}

export async function getProjectMembers(projectId: string): Promise<ScopedMembership[]> {
  return request<ScopedMembership[]>(`${API_BASE_URL}/projects/${projectId}/members`);
}

export async function putProjectMember(projectId: string, userId: string, role: string): Promise<ScopedMembership> {
  return request<ScopedMembership>(`${API_BASE_URL}/projects/${projectId}/members`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ user_id: userId, role }),
  });
}

export async function getModelConfiguration(scopeType: string, scopeId?: string): Promise<AIModelConfiguration | null> {
  const params = scopeId ? `?scope_id=${encodeURIComponent(scopeId)}` : '';
  return request<AIModelConfiguration | null>(`${API_BASE_URL}/admin/model-config/${scopeType}${params}`);
}

export async function putModelConfiguration(scopeType: string, scopeId: string | undefined, payload: AIModelConfiguration): Promise<AIModelConfiguration> {
  const params = scopeId ? `?scope_id=${encodeURIComponent(scopeId)}` : '';
  return request<AIModelConfiguration>(`${API_BASE_URL}/admin/model-config/${scopeType}${params}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  });
}

export async function getPromptConfiguration(promptKey: PromptConfiguration['prompt_key'], scopeType: string, scopeId?: string): Promise<PromptConfiguration | null> {
  const params = new URLSearchParams({ scope_type: scopeType });
  if (scopeId) params.set('scope_id', scopeId);
  return request<PromptConfiguration | null>(`${API_BASE_URL}/admin/prompt-config/${promptKey}?${params.toString()}`);
}

export async function getEffectivePromptConfiguration(promptKey: PromptConfiguration['prompt_key'], projectId: string, targetScope: 'app' | 'organization' | 'project' = 'project'): Promise<PromptConfiguration> {
  return request<PromptConfiguration>(`${API_BASE_URL}/admin/prompt-config/${promptKey}/effective?project_id=${encodeURIComponent(projectId)}&target_scope=${targetScope}`);
}

export async function getPromptConfigurationHistory(promptKey: PromptConfiguration['prompt_key'], scopeType: string, scopeId?: string): Promise<PromptConfigurationVersion[]> {
  const params = new URLSearchParams({ scope_type: scopeType });
  if (scopeId) params.set('scope_id', scopeId);
  return request<PromptConfigurationVersion[]>(`${API_BASE_URL}/admin/prompt-config/${promptKey}/history?${params.toString()}`);
}

export async function putPromptConfiguration(promptKey: PromptConfiguration['prompt_key'], scopeType: string, scopeId: string | undefined, payload: PromptConfiguration): Promise<PromptConfiguration> {
  const params = new URLSearchParams({ scope_type: scopeType });
  if (scopeId) params.set('scope_id', scopeId);
  return request<PromptConfiguration>(`${API_BASE_URL}/admin/prompt-config/${promptKey}?${params.toString()}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  });
}

export async function getAICostSummary(scopeType: 'organization' | 'project', scopeId: string): Promise<AICostSummary> {
  return request<AICostSummary>(`${API_BASE_URL}/admin/costs/${scopeType}/${scopeId}`);
}

export async function logout(): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/auth/logout`, { method: 'POST' });
  if (!response.ok && response.status !== 401) {
    await handleResponse<never>(response);
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  try {
    const response = await fetch(url, init);
    return handleResponse<T>(response);
  } catch (err) {
    if (err instanceof TypeError) {
      throw new Error(`Unable to reach API at ${API_BASE_URL}. Check that the backend is running and the dev proxy is active.`);
    }
    throw err;
  }
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const errorText = await response.text();
    const prefix = `${response.status} ${response.statusText} for ${response.url}`;
    try {
      const parsed = JSON.parse(errorText);
      if (typeof parsed.detail === 'string') {
        throw new Error(`${prefix}: ${parsed.detail}`);
      }
      if (parsed.detail?.message) {
        throw new Error(`${prefix}: ${parsed.detail.message}`);
      }
      throw new Error(`${prefix}: ${JSON.stringify(parsed.detail ?? parsed)}`);
    } catch (err) {
      if (err instanceof Error && err.name !== 'SyntaxError') {
        throw err;
      }
      throw new Error(`${prefix}${errorText ? `: ${errorText}` : ''}`);
    }
  }
  return response.json();
}

export async function getProjects(): Promise<ProjectSummary[]> {
  return request<ProjectSummary[]>(`${API_BASE_URL}/projects`, {
    headers: {
      'Content-Type': 'application/json',
    },
  });
}

export async function createProject(payload: ProjectCreatePayload): Promise<ProjectSummary> {
  const response = await fetch(`${API_BASE_URL}/projects`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });
  return handleResponse<ProjectSummary>(response);
}

export async function updateProject(projectId: string, payload: ProjectCreatePayload): Promise<ProjectSummary> {
  return request<ProjectSummary>(`${API_BASE_URL}/projects/${projectId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function getTestCases(
  projectId: string,
  filters: { search?: string; status?: string; source?: string } = {},
): Promise<TestCaseInventoryItem[]> {
  const params = new URLSearchParams({ project_id: projectId });
  if (filters.search) params.set('search', filters.search);
  if (filters.status) params.set('status', filters.status);
  if (filters.source) params.set('source', filters.source);
  return request<TestCaseInventoryItem[]>(`${API_BASE_URL}/test_cases?${params.toString()}`);
}

export async function getRequirements(
  search?: string,
  status?: string,
  projectId?: string,
): Promise<RequirementSummary[]> {
  const params = new URLSearchParams();
  if (search) params.set('search', search);
  if (status) params.set('status', status);
  if (projectId) params.set('project_id', projectId);

  const url = `${API_BASE_URL}/requirements${params.toString() ? `?${params.toString()}` : ''}`;
  return request<RequirementSummary[]>(url, {
    headers: {
      'Content-Type': 'application/json',
    },
  });
}

export async function getRequirement(id: string): Promise<RequirementDetail> {
  return request<RequirementDetail>(`${API_BASE_URL}/requirements/${id}`, {
    headers: {
      'Content-Type': 'application/json',
    },
  });
}

export async function getRequirementVersions(id: string): Promise<RequirementVersionSummary[]> {
  return request<RequirementVersionSummary[]>(`${API_BASE_URL}/requirements/${id}/versions`, {
    headers: {
      'Content-Type': 'application/json',
    },
  });
}

export async function createRequirement(
  payload: RequirementCreatePayload,
): Promise<RequirementDetail> {
  const response = await fetch(`${API_BASE_URL}/requirements`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });

  return handleResponse<RequirementDetail>(response);
}

export async function generateRequirementDraft(id: string): Promise<RequirementDetail> {
  return request<RequirementDetail>(`${API_BASE_URL}/requirements/${id}/generate`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
  });
}

export async function createBulkOperation(
  projectId: string,
  operationType: BulkOperationType,
  requirementIds: string[],
): Promise<BulkOperationJob> {
  const response = await fetch(`${API_BASE_URL}/requirements/bulk-operations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_id: projectId, operation_type: operationType, requirement_ids: requirementIds }),
  });
  return handleResponse<BulkOperationJob>(response);
}

export async function getBulkOperations(projectId: string): Promise<BulkOperationJob[]> {
  const params = new URLSearchParams({ project_id: projectId });
  return request<BulkOperationJob[]>(`${API_BASE_URL}/requirements/bulk-operations?${params.toString()}`, {
    headers: { 'Content-Type': 'application/json' },
  });
}

export async function getBulkOperation(jobId: string): Promise<BulkOperationJob> {
  return request<BulkOperationJob>(`${API_BASE_URL}/requirements/bulk-operations/${jobId}`, {
    headers: { 'Content-Type': 'application/json' },
  });
}

export async function bulkOperationAction(jobId: string, action: 'cancel' | 'pause' | 'resume' | 'retry-failed'): Promise<BulkOperationJob> {
  return request<BulkOperationJob>(`${API_BASE_URL}/requirements/bulk-operations/${jobId}/${action}`, { method: 'POST' });
}

export async function createScenarioForRequirement(
  requirementId: string,
  payload: TestScenarioCreatePayload,
): Promise<TestScenarioSummary> {
  const response = await fetch(`${API_BASE_URL}/requirements/${requirementId}/scenarios`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });
  return handleResponse<TestScenarioSummary>(response);
}

export async function createTestCaseForScenario(
  scenarioId: string,
  payload: TestCaseCreatePayload,
): Promise<TestCaseSummary> {
  const response = await fetch(`${API_BASE_URL}/scenarios/${scenarioId}/test_cases`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });
  return handleResponse<TestCaseSummary>(response);
}

export async function updateTestCase(
  testCaseId: string,
  payload: TestCaseUpdatePayload,
): Promise<TestCaseSummary> {
  return request<TestCaseSummary>(`${API_BASE_URL}/test_cases/${testCaseId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function appendTestCaseStep(
  testCaseId: string,
  payload: TestCaseStepCreatePayload,
): Promise<TestCaseStep> {
  const response = await fetch(`${API_BASE_URL}/test_cases/${testCaseId}/steps`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });
  return handleResponse<TestCaseStep>(response);
}

export async function approveRequirement(
  requirementId: string,
  payload: ApprovalActionPayload,
): Promise<RequirementDetail> {
  const response = await fetch(`${API_BASE_URL}/requirements/${requirementId}/approve`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });
  return handleResponse<RequirementDetail>(response);
}

export async function rejectRequirement(
  requirementId: string,
  payload: ApprovalActionPayload,
): Promise<RequirementDetail> {
  const response = await fetch(`${API_BASE_URL}/requirements/${requirementId}/reject`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });
  return handleResponse<RequirementDetail>(response);
}

export async function approveScenario(
  scenarioId: string,
  payload: ApprovalActionPayload,
): Promise<TestScenarioSummary> {
  const response = await fetch(`${API_BASE_URL}/scenarios/${scenarioId}/approve`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });
  return handleResponse<TestScenarioSummary>(response);
}

export async function rejectScenario(
  scenarioId: string,
  payload: ApprovalActionPayload,
): Promise<TestScenarioSummary> {
  const response = await fetch(`${API_BASE_URL}/scenarios/${scenarioId}/reject`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });
  return handleResponse<TestScenarioSummary>(response);
}

export async function approveTestCase(
  testCaseId: string,
  payload: ApprovalActionPayload,
): Promise<TestCaseSummary> {
  const response = await fetch(`${API_BASE_URL}/test_cases/${testCaseId}/approve`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });
  return handleResponse<TestCaseSummary>(response);
}

export async function bulkApproveTestCases(
  requirementId: string,
  payload: {
    scope: 'requirement' | 'scenario' | 'test_case';
    scenario_id?: string;
    test_case_ids?: string[];
    approved_by?: string;
    notes?: string;
  },
): Promise<BulkApprovalResult> {
  return request<BulkApprovalResult>(`${API_BASE_URL}/requirements/${requirementId}/test-cases/bulk-approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function rejectTestCase(
  testCaseId: string,
  payload: ApprovalActionPayload,
): Promise<TestCaseSummary> {
  const response = await fetch(`${API_BASE_URL}/test_cases/${testCaseId}/reject`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });
  return handleResponse<TestCaseSummary>(response);
}

export async function getProjectApprovalWorkflow(projectId: string): Promise<ApprovalWorkflow> {
  return request<ApprovalWorkflow>(`${API_BASE_URL}/projects/${projectId}/approval-workflow`);
}

export async function updateProjectApprovalWorkflow(
  projectId: string,
  payload: Omit<ApprovalWorkflow, 'project_id' | 'version' | 'updated_at'>,
): Promise<ApprovalWorkflow> {
  return request<ApprovalWorkflow>(`${API_BASE_URL}/projects/${projectId}/approval-workflow`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function getTestCaseApprovalWorkflow(testCaseId: string): Promise<ApprovalWorkflowRun | null> {
  return request<ApprovalWorkflowRun | null>(`${API_BASE_URL}/test_cases/${testCaseId}/approval-workflow`);
}

export async function createKnowledgeDocument(
  projectId: string,
  payload: { title: string; content: string; source?: string },
): Promise<KnowledgeDocument> {
  return request<KnowledgeDocument>(`${API_BASE_URL}/projects/${projectId}/knowledge-documents`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function getKnowledgeDocuments(projectId: string): Promise<KnowledgeDocument[]> {
  return request<KnowledgeDocument[]>(`${API_BASE_URL}/projects/${projectId}/knowledge-documents`);
}

export async function createFeedback(
  payload: FeedbackCreatePayload,
): Promise<FeedbackSummary> {
  const response = await fetch(`${API_BASE_URL}/feedback`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });
  return handleResponse<FeedbackSummary>(response);
}

export async function getFeedback(
  targetLevel?: string,
  targetId?: string,
): Promise<FeedbackSummary[]> {
  const params = new URLSearchParams();
  if (targetLevel) params.set('target_level', targetLevel);
  if (targetId) params.set('target_id', targetId);
  const url = `${API_BASE_URL}/feedback${params.toString() ? `?${params.toString()}` : ''}`;
  const response = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
    },
  });
  return handleResponse<FeedbackSummary[]>(response);
}

export async function processFeedbackRevision(
  payload: FeedbackRevisionPayload,
): Promise<RevisionRecordSummary> {
  const response = await fetch(`${API_BASE_URL}/feedback/revise`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });
  return handleResponse<RevisionRecordSummary>(response);
}

export async function getRevisions(
  targetLevel?: string,
  targetId?: string,
  feedbackId?: string,
): Promise<RevisionRecordSummary[]> {
  const params = new URLSearchParams();
  if (targetLevel) params.set('target_level', targetLevel);
  if (targetId) params.set('target_id', targetId);
  if (feedbackId) params.set('feedback_id', feedbackId);
  const url = `${API_BASE_URL}/revisions${params.toString() ? `?${params.toString()}` : ''}`;
  const response = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
    },
  });
  return handleResponse<RevisionRecordSummary[]>(response);
}

export async function getApprovals(
  targetLevel?: string,
  targetId?: string,
): Promise<ApprovalRecordSummary[]> {
  const params = new URLSearchParams();
  if (targetLevel) params.set('target_level', targetLevel);
  if (targetId) params.set('target_id', targetId);
  const url = `${API_BASE_URL}/approvals${params.toString() ? `?${params.toString()}` : ''}`;
  const response = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
    },
  });
  return handleResponse<ApprovalRecordSummary[]>(response);
}

export async function getAudit(
  entityType?: string,
  entityId?: string,
  scopeType?: 'app' | 'organization' | 'project',
  scopeId?: string,
): Promise<AuditLogSummary[]> {
  const params = new URLSearchParams();
  if (entityType) params.set('entity_type', entityType);
  if (entityId) params.set('entity_id', entityId);
  if (scopeType) params.set('scope_type', scopeType);
  if (scopeId) params.set('scope_id', scopeId);
  const url = `${API_BASE_URL}/audit${params.toString() ? `?${params.toString()}` : ''}`;
  const response = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
    },
  });
  return handleResponse<AuditLogSummary[]>(response);
}

export async function getTestCaseVersions(testCaseId: string): Promise<TestCaseVersionSummary[]> {
  const response = await fetch(`${API_BASE_URL}/test_cases/${testCaseId}/versions`, {
    headers: {
      'Content-Type': 'application/json',
    },
  });
  return handleResponse<TestCaseVersionSummary[]>(response);
}

export async function validateTarget(targetLevel: string, targetId: string): Promise<ValidationResult> {
  const response = await fetch(`${API_BASE_URL}/validate/${targetLevel}/${targetId}`, {
    headers: {
      'Content-Type': 'application/json',
    },
  });
  return handleResponse<ValidationResult>(response);
}

export async function evaluateQuality(
  targetLevel: string,
  targetId: string,
): Promise<QualityEvaluationSummary> {
  const response = await fetch(`${API_BASE_URL}/quality/${targetLevel}/${targetId}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
  });
  return handleResponse<QualityEvaluationSummary>(response);
}

export async function getQualityEvaluations(
  targetLevel?: string,
  targetId?: string,
): Promise<QualityEvaluationSummary[]> {
  const params = new URLSearchParams();
  if (targetLevel) params.set('target_level', targetLevel);
  if (targetId) params.set('target_id', targetId);
  const url = `${API_BASE_URL}/quality${params.toString() ? `?${params.toString()}` : ''}`;
  const response = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
    },
  });
  return handleResponse<QualityEvaluationSummary[]>(response);
}

export async function getRequirementImpact(requirementId: string): Promise<ImpactAnalysisSummary> {
  const response = await fetch(`${API_BASE_URL}/requirements/${requirementId}/impact`, {
    headers: {
      'Content-Type': 'application/json',
    },
  });
  return handleResponse<ImpactAnalysisSummary>(response);
}

export async function getScenarioImpact(scenarioId: string): Promise<ImpactAnalysisSummary> {
  const response = await fetch(`${API_BASE_URL}/scenarios/${scenarioId}/impact`, { headers: { 'Content-Type': 'application/json' } });
  return handleResponse<ImpactAnalysisSummary>(response);
}

export async function getTestCaseImpact(testCaseId: string): Promise<ImpactAnalysisSummary> {
  const response = await fetch(`${API_BASE_URL}/test_cases/${testCaseId}/impact`, { headers: { 'Content-Type': 'application/json' } });
  return handleResponse<ImpactAnalysisSummary>(response);
}

export async function getImpactAnalyses(targetId: string, targetLevel: 'requirement' | 'scenario' | 'test_case'): Promise<ImpactAnalysisSummary[]> {
  const params = new URLSearchParams({ target_level: targetLevel, target_id: targetId });
  return request<ImpactAnalysisSummary[]>(`${API_BASE_URL}/impact?${params.toString()}`);
}

export async function analyzeImpact(payload: ImpactAnalyzePayload): Promise<ImpactAnalysisSummary> {
  const response = await fetch(`${API_BASE_URL}/impact/analyze`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });
  return handleResponse<ImpactAnalysisSummary>(response);
}

export async function createSemanticCalibration(
  projectId: string,
  samples: SemanticCalibrationSample[],
  apply: boolean,
): Promise<SemanticCalibrationSummary> {
  const response = await fetch(`${API_BASE_URL}/impact/calibrations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_id: projectId, samples, apply }),
  });
  return handleResponse<SemanticCalibrationSummary>(response);
}

export async function getSemanticCalibrations(projectId: string): Promise<SemanticCalibrationSummary[]> {
  const params = new URLSearchParams({ project_id: projectId });
  return request<SemanticCalibrationSummary[]>(`${API_BASE_URL}/impact/calibrations?${params.toString()}`);
}

export async function getComplianceProfile(projectId: string): Promise<ComplianceProfile> {
  return request<ComplianceProfile>(`${API_BASE_URL}/compliance/projects/${projectId}/profile`);
}

export async function updateComplianceProfile(
  projectId: string,
  profile: Omit<ComplianceProfile, 'project_id' | 'updated_at'>,
): Promise<ComplianceProfile> {
  const response = await fetch(`${API_BASE_URL}/compliance/projects/${projectId}/profile`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(profile),
  });
  return handleResponse<ComplianceProfile>(response);
}

export async function exportComplianceEvidence(projectId: string): Promise<ComplianceEvidenceExport> {
  return request<ComplianceEvidenceExport>(`${API_BASE_URL}/compliance/projects/${projectId}/evidence`);
}

export async function deprecateImpactedTestCase(
  testCaseId: string,
  payload: ApprovalActionPayload,
): Promise<TestCaseSummary> {
  const response = await fetch(`${API_BASE_URL}/impact/test_cases/${testCaseId}/deprecate`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });
  return handleResponse<TestCaseSummary>(response);
}

export async function flagImpactedTestCaseForUpdate(
  testCaseId: string,
  payload: ApprovalActionPayload,
): Promise<TestCaseSummary> {
  const response = await fetch(`${API_BASE_URL}/impact/test_cases/${testCaseId}/review-update`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });
  return handleResponse<TestCaseSummary>(response);
}

export async function importJiraRequirements(
  projectId: string,
  jql: string,
  maxResults = 100,
  requestedBy = 'system',
): Promise<IntegrationRunSummary> {
  const response = await fetch(`${API_BASE_URL}/integrations/jira/import`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ project_id: projectId, jql, max_results: maxResults, requested_by: requestedBy }),
  });
  return handleResponse<IntegrationRunSummary>(response);
}

export function getIntegrationSchedules(projectId: string): Promise<IntegrationSchedule[]> {
  const params = new URLSearchParams({ project_id: projectId });
  return request<IntegrationSchedule[]>(`${API_BASE_URL}/integrations/schedules?${params.toString()}`);
}

export function createJiraSchedule(payload: {
  project_id: string;
  name: string;
  jql: string;
  interval_seconds: number;
}): Promise<IntegrationSchedule> {
  return request<IntegrationSchedule>(`${API_BASE_URL}/integrations/schedules`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      project_id: payload.project_id,
      name: payload.name,
      integration_type: 'jira',
      configuration: { jql: payload.jql, max_results: 1000 },
      interval_seconds: payload.interval_seconds,
      enabled: true,
    }),
  });
}

export function triggerIntegrationSchedule(scheduleId: string): Promise<IntegrationSchedule> {
  return request<IntegrationSchedule>(`${API_BASE_URL}/integrations/schedules/${scheduleId}/run`, {
    method: 'POST',
  });
}

export async function importRequirementFile(
  projectId: string,
  file: File,
): Promise<IntegrationRunSummary> {
  const body = new FormData();
  body.set('project_id', projectId);
  body.set('file', file);
  const response = await fetch(`${API_BASE_URL}/requirements/import-file`, {
    method: 'POST',
    body,
  });
  return handleResponse<IntegrationRunSummary>(response);
}

export async function importHistoricalTestCases(
  projectId: string,
  file: File,
): Promise<IntegrationRunSummary> {
  const body = new FormData();
  body.set('project_id', projectId);
  body.set('file', file);
  const response = await fetch(`${API_BASE_URL}/test-cases/import-file`, {
    method: 'POST',
    body,
  });
  return handleResponse<IntegrationRunSummary>(response);
}

export async function getImportMappingProfiles(projectId: string): Promise<ImportMappingProfile[]> {
  const params = new URLSearchParams({ project_id: projectId });
  return request<ImportMappingProfile[]>(`${API_BASE_URL}/import-mappings?${params.toString()}`);
}

export async function getImportMappingProfileHistory(projectId: string): Promise<ImportMappingProfile[]> {
  const params = new URLSearchParams({ project_id: projectId, include_history: 'true' });
  return request<ImportMappingProfile[]>(`${API_BASE_URL}/import-mappings?${params.toString()}`);
}

export async function updateImportMappingProfile(
  profileId: string,
  payload: { name: string; configuration: Record<string, unknown>; active: boolean },
): Promise<ImportMappingProfile> {
  const response = await fetch(`${API_BASE_URL}/import-mappings/${profileId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return handleResponse<ImportMappingProfile>(response);
}

export async function rollbackImportMappingProfile(profileId: string): Promise<ImportMappingProfile> {
  const response = await fetch(`${API_BASE_URL}/import-mappings/${profileId}/rollback`, { method: 'POST' });
  return handleResponse<ImportMappingProfile>(response);
}

export async function createImportMappingProfile(payload: {
  project_id: string;
  name: string;
  entity_type: 'requirement' | 'test_case';
  configuration: Record<string, unknown>;
  active: boolean;
}): Promise<ImportMappingProfile> {
  const response = await fetch(`${API_BASE_URL}/import-mappings`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return handleResponse<ImportMappingProfile>(response);
}

async function mappedImportRequest<T>(path: string, profileId: string, file: File): Promise<T> {
  const body = new FormData();
  body.set('profile_id', profileId);
  body.set('file', file);
  const response = await fetch(`${API_BASE_URL}${path}`, { method: 'POST', body });
  return handleResponse<T>(response);
}

export function previewMappedImport(profileId: string, file: File): Promise<MappedImportPreview> {
  return mappedImportRequest<MappedImportPreview>('/imports/mapped/preview', profileId, file);
}

export function executeMappedImport(profileId: string, file: File): Promise<IntegrationRunSummary> {
  return mappedImportRequest<IntegrationRunSummary>('/imports/mapped', profileId, file);
}

export function createMappedImportJob(profileId: string, file: File): Promise<MappedImportJob> {
  return mappedImportRequest<MappedImportJob>('/imports/mapped/jobs', profileId, file);
}

export function getMappedImportJobs(projectId: string): Promise<MappedImportJob[]> {
  const params = new URLSearchParams({ project_id: projectId });
  return request<MappedImportJob[]>(`${API_BASE_URL}/imports/mapped/jobs?${params.toString()}`);
}

export async function retryMappedImportJob(jobId: string): Promise<MappedImportJob> {
  const response = await fetch(`${API_BASE_URL}/imports/mapped/jobs/${jobId}/retry`, { method: 'POST' });
  return handleResponse<MappedImportJob>(response);
}

export function getUnresolvedImports(projectId: string): Promise<UnresolvedImportRecord[]> {
  const params = new URLSearchParams({ project_id: projectId, status: 'pending' });
  return request<UnresolvedImportRecord[]>(`${API_BASE_URL}/imports/unresolved?${params.toString()}`);
}

export function retryUnresolvedImport(recordId: string): Promise<UnresolvedImportRecord> {
  return request<UnresolvedImportRecord>(`${API_BASE_URL}/imports/unresolved/${recordId}/retry`, {
    method: 'POST',
  });
}

export function dismissUnresolvedImport(recordId: string): Promise<UnresolvedImportRecord> {
  return request<UnresolvedImportRecord>(`${API_BASE_URL}/imports/unresolved/${recordId}/dismiss`, {
    method: 'POST',
  });
}

export async function syncTestRepository(
  projectId: string,
  repository: string,
  branch = 'main',
  requestedBy = 'system',
): Promise<RepositorySyncRunSummary> {
  const response = await fetch(`${API_BASE_URL}/integrations/test-repo/sync`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ project_id: projectId, repository, branch, requested_by: requestedBy }),
  });
  return handleResponse<RepositorySyncRunSummary>(response);
}

export async function getExecutionCandidates(projectId: string): Promise<TestCaseSummary[]> {
  const params = new URLSearchParams({ project_id: projectId });
  return request<TestCaseSummary[]>(`${API_BASE_URL}/executions/candidates?${params.toString()}`);
}

export async function getTestExecutions(projectId: string): Promise<TestExecutionRunSummary[]> {
  const params = new URLSearchParams({ project_id: projectId });
  return request<TestExecutionRunSummary[]>(`${API_BASE_URL}/executions?${params.toString()}`);
}

export async function queueTestExecutions(
  projectId: string,
  testCaseIds: string[],
  environment: string,
): Promise<TestExecutionRunSummary[]> {
  const response = await fetch(`${API_BASE_URL}/executions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      project_id: projectId,
      test_case_ids: testCaseIds,
      environment,
      request_id: crypto.randomUUID(),
    }),
  });
  return handleResponse<TestExecutionRunSummary[]>(response);
}

export async function cleanupRequirementText(text: string): Promise<CleanupResult> {
  const response = await fetch(`${API_BASE_URL}/nlp/cleanup`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ text }),
  });
  return handleResponse<CleanupResult>(response);
}

export async function runEvaluationSuite(
  suite = 'quality',
  requestedBy = 'system',
): Promise<EvaluationRunSummary> {
  const response = await fetch(`${API_BASE_URL}/evals/run`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ suite, requested_by: requestedBy }),
  });
  return handleResponse<EvaluationRunSummary>(response);
}

export async function getMonitoringSummary(): Promise<MonitoringSummary> {
  const response = await fetch(`${API_BASE_URL}/monitoring/summary`, {
    headers: {
      'Content-Type': 'application/json',
    },
  });
  return handleResponse<MonitoringSummary>(response);
}

export async function getDependencyHealth(): Promise<DependencyHealthSummary> {
  return request<DependencyHealthSummary>(`${API_BASE_URL}/operations/dependencies`, {
    headers: { 'Content-Type': 'application/json' },
  });
}

export async function getOutboxEvents(status?: OutboxEventSummary['status']): Promise<OutboxEventSummary[]> {
  const params = new URLSearchParams();
  if (status) params.set('status', status);
  return request<OutboxEventSummary[]>(
    `${API_BASE_URL}/operations/outbox${params.toString() ? `?${params.toString()}` : ''}`,
    { headers: { 'Content-Type': 'application/json' } },
  );
}

export async function retryOutboxEvent(eventId: string): Promise<OutboxEventSummary> {
  const response = await fetch(`${API_BASE_URL}/operations/outbox/${eventId}/retry`, { method: 'POST' });
  return handleResponse<OutboxEventSummary>(response);
}

export async function getAlerts(projectId?: string): Promise<AlertSummary[]> {
  const params = new URLSearchParams();
  if (projectId) params.set('project_id', projectId);
  return request<AlertSummary[]>(
    `${API_BASE_URL}/operations/alerts${params.toString() ? `?${params.toString()}` : ''}`,
  );
}

export async function acknowledgeAlert(alertId: string): Promise<AlertSummary> {
  const response = await fetch(`${API_BASE_URL}/operations/alerts/${alertId}/acknowledge`, { method: 'POST' });
  return handleResponse<AlertSummary>(response);
}

export async function createGovernancePolicy(
  payload: {
    name: string;
    policy_type: string;
    rules: Record<string, unknown>;
    created_by: string;
    status?: string;
  },
): Promise<GovernancePolicySummary> {
  const response = await fetch(`${API_BASE_URL}/governance/policies`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });
  return handleResponse<GovernancePolicySummary>(response);
}

export async function getGovernancePolicies(): Promise<GovernancePolicySummary[]> {
  const response = await fetch(`${API_BASE_URL}/governance/policies`, {
    headers: {
      'Content-Type': 'application/json',
    },
  });
  return handleResponse<GovernancePolicySummary[]>(response);
}
