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
};

export type TestScenarioSummary = {
  id: string;
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

export type RequirementSummary = {
  id: string;
  external_id?: string;
  title: string;
  description?: string;
  source: string;
  status: string;
  metadata_json?: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
};

export type RequirementDetail = RequirementSummary & {
  scenarios?: TestScenarioSummary[];
};

export type RequirementCreatePayload = {
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

export type TestCaseStepCreatePayload = {
  step_number: number;
  action: string;
  expected_result: string;
};

export type ApprovalActionPayload = {
  approved_by?: string;
  notes?: string;
};

export type FeedbackCreatePayload = {
  target_level: string;
  target_id: string;
  source: string;
  feedback_type: string;
  comment: string;
  created_by: string;
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
  context_ids?: string[];
  created_by: string;
};

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

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1';

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const errorText = await response.text();
    try {
      const parsed = JSON.parse(errorText);
      if (typeof parsed.detail === 'string') {
        throw new Error(parsed.detail);
      }
      if (parsed.detail?.message) {
        throw new Error(parsed.detail.message);
      }
      throw new Error(JSON.stringify(parsed.detail ?? parsed));
    } catch (err) {
      if (err instanceof Error && err.name !== 'SyntaxError') {
        throw err;
      }
      throw new Error(errorText || response.statusText);
    }
  }
  return response.json();
}

export async function getRequirements(search?: string, status?: string): Promise<RequirementSummary[]> {
  const params = new URLSearchParams();
  if (search) params.set('search', search);
  if (status) params.set('status', status);

  const url = `${API_BASE_URL}/requirements${params.toString() ? `?${params.toString()}` : ''}`;
  const response = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
    },
  });

  return handleResponse<RequirementSummary[]>(response);
}

export async function getRequirement(id: string): Promise<RequirementDetail> {
  const response = await fetch(`${API_BASE_URL}/requirements/${id}`, {
    headers: {
      'Content-Type': 'application/json',
    },
  });

  return handleResponse<RequirementDetail>(response);
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
  const response = await fetch(`${API_BASE_URL}/requirements/${id}/generate`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
  });

  return handleResponse<RequirementDetail>(response);
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
): Promise<AuditLogSummary[]> {
  const params = new URLSearchParams();
  if (entityType) params.set('entity_type', entityType);
  if (entityId) params.set('entity_id', entityId);
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
  folderPath: string,
  requestedBy = 'system',
): Promise<IntegrationRunSummary> {
  const response = await fetch(`${API_BASE_URL}/integrations/jira/import`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ folder_path: folderPath, requested_by: requestedBy }),
  });
  return handleResponse<IntegrationRunSummary>(response);
}

export async function syncTestRepository(
  repository: string,
  branch = 'main',
  requestedBy = 'system',
): Promise<RepositorySyncRunSummary> {
  const response = await fetch(`${API_BASE_URL}/integrations/test-repo/sync`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ repository, branch, requested_by: requestedBy }),
  });
  return handleResponse<RepositorySyncRunSummary>(response);
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
