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

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1';

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(errorText || response.statusText);
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
