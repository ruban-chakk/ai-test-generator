import { expect, test } from '@playwright/test';


test('admin can inspect operations and import a requirement file', async ({ page }) => {
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const now = '2026-10-21T00:00:00Z';
    let body: unknown;

    if (path.endsWith('/auth/me')) {
      body = { id: 'user-1', username: 'admin', email: 'admin@example.com', role: 'admin', active: true };
    } else if (path.endsWith('/projects')) {
      body = [{ id: 'project-1', name: 'Payments', status: 'active', requirement_count: 2, test_case_count: 4 }];
    } else if (path.endsWith('/monitoring/summary')) {
      body = { status: 'ok', metrics: { requirements: 2, outbox_failed: 1 }, captured_at: now };
    } else if (path.endsWith('/governance/policies')) {
      body = [];
    } else if (path.endsWith('/operations/dependencies')) {
      body = {
        status: 'degraded',
        checked_at: now,
        dependencies: [
          { name: 'llm', status: 'healthy', configured: true },
          { name: 'jira', status: 'not_configured', configured: false },
        ],
      };
    } else if (path.endsWith('/operations/outbox')) {
      body = [{
        id: 'event-1', event_type: 'test_case.index_requested', aggregate_type: 'test_case',
        aggregate_id: 'case-1', status: 'failed', attempts: 8, last_error: 'GenerationProviderError',
        available_at: now, created_at: now,
      }];
    } else if (path.endsWith('/operations/alerts')) {
      body = [{
        id: 'alert-1', project_id: 'project-1', category: 'outbox_exhausted', severity: 'critical',
        title: 'Delivery exhausted', details: { event_id: 'event-1' }, status: 'open',
        delivery_status: 'not_configured', created_at: now,
      }];
    } else if (path.endsWith('/compliance/projects/project-1/profile')) {
      body = {
        project_id: 'project-1', frameworks: ['SOC2'], evidence_retention_days: 365,
        evidence_export_enabled: true, pseudonymize_actors: true, approval_notes_required: false,
      };
    } else if (path.endsWith('/impact/calibrations') && request.method() === 'GET') {
      body = [];
    } else if (path.endsWith('/impact/calibrations') && request.method() === 'POST') {
      body = {
        id: 'calibration-1', project_id: 'project-1', dataset_digest: 'digest', sample_count: 10,
        label_distribution: { duplicate: 3, update: 3, unrelated: 4 },
        previous_thresholds: { duplicate: 0.8, update: 0.45 },
        proposed_thresholds: { duplicate: 0.86, update: 0.57 },
        metrics: { accuracy: 1, macro_f1: 1, confusion: {} }, status: 'applied',
        requested_by: 'admin', created_at: now, applied_at: now,
      };
    } else if (path.endsWith('/requirements/import-file') && request.method() === 'POST') {
      body = {
        id: 'run-1', integration_type: 'file_import', status: 'completed', requested_by: 'admin',
        parameters: {}, result: { created_count: 1, existing_count: 0 }, started_at: now, completed_at: now,
      };
    } else {
      return route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: path }) });
    }
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });

  await page.goto('/operations');
  await expect(page.getByRole('heading', { name: 'Integrations and governance' })).toBeVisible();
  await expect(page.getByText('Overall: degraded')).toBeVisible();
  await expect(page.getByText('GenerationProviderError')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Project compliance' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Semantic calibration' })).toBeVisible();

  await page.getByLabel('Requirement file').setInputFiles({
    name: 'refunds.md',
    mimeType: 'text/markdown',
    buffer: Buffer.from('# Refunds\nUsers can request a refund.'),
  });
  await page.getByRole('button', { name: 'Import file' }).click();
  await expect(page.getByText(/Created 1/)).toBeVisible();
});

test('approver can queue an approved test case for automated execution', async ({ page }) => {
  let queued = false;
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const now = '2026-10-21T00:00:00Z';
    let body: unknown;

    if (path.endsWith('/auth/config')) {
      body = { oidc_enabled: false };
    } else if (path.endsWith('/auth/me')) {
      body = { id: 'user-2', username: 'approver', email: 'approver@example.com', role: 'approver', active: true };
    } else if (path.endsWith('/projects')) {
      body = [{ id: 'project-1', name: 'Payments', status: 'active', requirement_count: 1, test_case_count: 1 }];
    } else if (path.endsWith('/executions/candidates')) {
      body = [{
        id: 'case-1', title: 'Reject expired token', description: 'Expired tokens are rejected.',
        status: 'approved', version: 2, locked: true, repository_status: 'synced',
        steps: [{ step_number: 1, action: 'Open token', expected_result: 'Rejected' }],
      }];
    } else if (path.endsWith('/executions') && request.method() === 'POST') {
      const payload = request.postDataJSON();
      expect(payload.project_id).toBe('project-1');
      expect(payload.test_case_ids).toEqual(['case-1']);
      expect(payload.environment).toBe('staging');
      queued = true;
      body = [];
    } else if (path.endsWith('/executions')) {
      body = queued ? [{
        id: 'run-1', project_id: 'project-1', test_case_id: 'case-1', test_case_version: 2,
        environment: 'staging', runner: 'generic', status: 'queued', result: {},
        requested_by: 'approver', created_at: now,
      }] : [];
    } else {
      return route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: path }) });
    }
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });

  await page.goto('/executions');
  await expect(page.getByRole('heading', { name: 'Test executions' })).toBeVisible();
  await page.getByRole('checkbox').check();
  await page.getByRole('button', { name: 'Run selected (1)' }).click();
  await expect(page.getByText('queued')).toBeVisible();
});

test('reviewer can run project-scoped semantic search and open a linked requirement', async ({ page }) => {
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    let body: unknown;
    if (path.endsWith('/auth/config')) {
      body = { oidc_enabled: false };
    } else if (path.endsWith('/auth/me')) {
      body = { id: 'user-3', username: 'reviewer', email: 'reviewer@example.com', role: 'reviewer', active: true };
    } else if (path.endsWith('/projects')) {
      body = [{ id: 'project-1', name: 'Payments', status: 'active', requirement_count: 1, test_case_count: 1 }];
    } else if (path.endsWith('/search')) {
      expect(url.searchParams.get('project_id')).toBe('project-1');
      expect(url.searchParams.get('query')).toBe('expired reset token');
      expect(url.searchParams.get('entity_type')).toBe('test_case');
      body = [{
        vector_id: 'test_case:case-1:v2', entity_type: 'test_case', entity_id: 'case-1',
        title: 'Reject expired reset token', text: 'Expired reset links are rejected.', score: 0.92,
        metadata: { requirement_id: 'requirement-1' },
      }];
    } else if (path.endsWith('/requirements/requirement-1')) {
      body = {
        id: 'requirement-1', project_id: 'project-1', title: 'Secure password reset',
        description: 'Reset links expire and cannot be reused.', source: 'manual', status: 'approved', scenarios: [],
      };
    } else {
      return route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: path }) });
    }
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });

  await page.goto('/search');
  await page.getByRole('searchbox').fill('expired reset token');
  await page.getByLabel('Artifact type').selectOption('test_case');
  await page.getByRole('button', { name: 'Search' }).click();
  await expect(page.getByRole('heading', { name: 'Reject expired reset token' })).toBeVisible();
  await expect(page.getByText('92%')).toBeVisible();
  await page.getByRole('link', { name: 'Open requirement' }).click();
  await expect(page.getByRole('heading', { name: 'Secure password reset' })).toBeVisible();
});
