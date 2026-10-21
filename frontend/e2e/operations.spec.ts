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
