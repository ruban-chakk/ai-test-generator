import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import OperationsPage from './Operations';
import {
  getDependencyHealth,
  getGovernancePolicies,
  getMonitoringSummary,
  getOutboxEvents,
  importRequirementFile,
  retryOutboxEvent,
} from '../api';

vi.mock('../api', () => ({
  cleanupRequirementText: vi.fn(),
  createGovernancePolicy: vi.fn(),
  getDependencyHealth: vi.fn(),
  getGovernancePolicies: vi.fn(),
  getMonitoringSummary: vi.fn(),
  getOutboxEvents: vi.fn(),
  importJiraRequirements: vi.fn(),
  importRequirementFile: vi.fn(),
  retryOutboxEvent: vi.fn(),
  runEvaluationSuite: vi.fn(),
  syncTestRepository: vi.fn(),
}));

const project = {
  id: 'project-1',
  name: 'Payments',
  status: 'active',
  requirement_count: 2,
  test_case_count: 4,
};

function mockRefresh() {
  vi.mocked(getMonitoringSummary).mockResolvedValue({
    status: 'ok',
    metrics: { requirements: 2 },
    captured_at: '2026-10-21T00:00:00Z',
  });
  vi.mocked(getGovernancePolicies).mockResolvedValue([]);
  vi.mocked(getDependencyHealth).mockResolvedValue({
    status: 'degraded',
    checked_at: '2026-10-21T00:00:00Z',
    dependencies: [{ name: 'jira', status: 'not_configured', configured: false }],
  });
  vi.mocked(getOutboxEvents).mockResolvedValue([
    {
      id: 'event-1',
      event_type: 'test_case.index_requested',
      aggregate_type: 'test_case',
      aggregate_id: 'case-1',
      status: 'failed',
      attempts: 8,
      available_at: '2026-10-21T00:00:00Z',
      created_at: '2026-10-21T00:00:00Z',
      last_error: 'GenerationProviderError',
    },
  ]);
}

describe('OperationsPage', () => {
  beforeEach(() => {
    mockRefresh();
  });

  it('renders dependency and failed-delivery state and requeues an event', async () => {
    const user = userEvent.setup();
    vi.mocked(retryOutboxEvent).mockResolvedValue({
      id: 'event-1',
      event_type: 'test_case.index_requested',
      aggregate_type: 'test_case',
      aggregate_id: 'case-1',
      status: 'pending',
      attempts: 0,
      available_at: '2026-10-21T00:00:00Z',
      created_at: '2026-10-21T00:00:00Z',
    });

    render(<MemoryRouter><OperationsPage selectedProject={project} /></MemoryRouter>);

    expect(await screen.findByText('not configured')).toBeInTheDocument();
    expect(screen.getByText('GenerationProviderError')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Retry event' }));
    await waitFor(() => expect(retryOutboxEvent).toHaveBeenCalledWith('event-1'));
  });

  it('uploads a selected requirement file into the active project', async () => {
    const user = userEvent.setup();
    vi.mocked(importRequirementFile).mockResolvedValue({
      id: 'run-1',
      integration_type: 'file_import',
      status: 'completed',
      requested_by: 'admin',
      parameters: {},
      result: { created_count: 1, existing_count: 0 },
      started_at: '2026-10-21T00:00:00Z',
      completed_at: '2026-10-21T00:00:01Z',
    });
    render(<MemoryRouter><OperationsPage selectedProject={project} /></MemoryRouter>);
    await screen.findByText('not configured');

    const file = new File(['# Refunds\nUsers can request a refund.'], 'refunds.md', { type: 'text/markdown' });
    const fileInput = screen.getByLabelText('Requirement file');
    await user.upload(fileInput, file);
    fireEvent.submit(fileInput.closest('form')!);

    await waitFor(() => expect(importRequirementFile).toHaveBeenCalledWith('project-1', file));
    expect(await screen.findByText(/Created 1/)).toBeInTheDocument();
  });
});
