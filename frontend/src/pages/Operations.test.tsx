import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import OperationsPage from './Operations';
import {
  acknowledgeAlert,
  createSemanticCalibration,
  exportComplianceEvidence,
  getAlerts,
  getComplianceProfile,
  getDependencyHealth,
  getGovernancePolicies,
  getMonitoringSummary,
  getOutboxEvents,
  getSemanticCalibrations,
  importRequirementFile,
  retryOutboxEvent,
  updateComplianceProfile,
} from '../api';

vi.mock('../api', () => ({
  acknowledgeAlert: vi.fn(),
  cleanupRequirementText: vi.fn(),
  createGovernancePolicy: vi.fn(),
  getDependencyHealth: vi.fn(),
  getAlerts: vi.fn(),
  getComplianceProfile: vi.fn(),
  getGovernancePolicies: vi.fn(),
  getMonitoringSummary: vi.fn(),
  getOutboxEvents: vi.fn(),
  getSemanticCalibrations: vi.fn(),
  createSemanticCalibration: vi.fn(),
  updateComplianceProfile: vi.fn(),
  exportComplianceEvidence: vi.fn(),
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
  vi.mocked(getAlerts).mockResolvedValue([
    {
      id: 'alert-1',
      project_id: 'project-1',
      category: 'test_execution_failed',
      severity: 'high',
      title: 'Automated test execution failed',
      details: { execution_run_id: 'run-1' },
      status: 'open',
      delivery_status: 'not_configured',
      created_at: '2026-10-21T00:00:00Z',
    },
  ]);
  vi.mocked(getComplianceProfile).mockResolvedValue({
    project_id: 'project-1',
    frameworks: ['SOC2'],
    evidence_retention_days: 365,
    evidence_export_enabled: true,
    pseudonymize_actors: true,
    approval_notes_required: false,
  });
  vi.mocked(getSemanticCalibrations).mockResolvedValue([]);
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

  it('renders and acknowledges an operational alert', async () => {
    const user = userEvent.setup();
    vi.mocked(acknowledgeAlert).mockResolvedValue({
      id: 'alert-1',
      project_id: 'project-1',
      category: 'test_execution_failed',
      severity: 'high',
      title: 'Automated test execution failed',
      details: { execution_run_id: 'run-1' },
      status: 'acknowledged',
      delivery_status: 'not_configured',
      acknowledged_by: 'admin',
      acknowledged_at: '2026-10-21T00:01:00Z',
      created_at: '2026-10-21T00:00:00Z',
    });
    render(<MemoryRouter><OperationsPage selectedProject={project} /></MemoryRouter>);

    expect(await screen.findByText('Automated test execution failed')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Acknowledge' }));
    await waitFor(() => expect(acknowledgeAlert).toHaveBeenCalledWith('alert-1'));
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

  it('applies project compliance controls, exports evidence, and calibrates thresholds', async () => {
    const user = userEvent.setup();
    vi.mocked(updateComplianceProfile).mockResolvedValue({
      project_id: 'project-1', frameworks: ['SOC2'], evidence_retention_days: 365,
      evidence_export_enabled: true, pseudonymize_actors: true, approval_notes_required: true,
    });
    vi.mocked(exportComplianceEvidence).mockResolvedValue({
      project_id: 'project-1', generated_at: '2026-10-21T00:00:00Z',
      period_start: '2025-10-21T00:00:00Z', period_end: '2026-10-21T00:00:00Z',
      profile: {
        project_id: 'project-1', frameworks: ['SOC2'], evidence_retention_days: 365,
        evidence_export_enabled: true, pseudonymize_actors: true, approval_notes_required: true,
      },
      evidence: {}, record_counts: {}, is_complete: true, truncated_sections: [], sha256: 'a'.repeat(64),
    });
    vi.mocked(createSemanticCalibration).mockResolvedValue({
      id: 'calibration-1', project_id: 'project-1', dataset_digest: 'digest', sample_count: 10,
      label_distribution: { duplicate: 3, update: 3, unrelated: 4 },
      previous_thresholds: { duplicate: 0.8, update: 0.45 },
      proposed_thresholds: { duplicate: 0.86, update: 0.57 },
      metrics: { accuracy: 1, macro_f1: 1, confusion: {} }, status: 'applied',
      requested_by: 'admin', created_at: '2026-10-21T00:00:00Z',
    });
    render(<MemoryRouter><OperationsPage selectedProject={project} /></MemoryRouter>);
    await screen.findByText('Active retention: 365 days');

    await user.click(screen.getByLabelText('Require approval notes'));
    await user.click(screen.getByRole('button', { name: 'Save compliance profile' }));
    await waitFor(() => expect(updateComplianceProfile).toHaveBeenCalledWith(
      'project-1', expect.objectContaining({ approval_notes_required: true }),
    ));

    await user.click(screen.getByRole('button', { name: 'Generate evidence export' }));
    expect(await screen.findByText(/Evidence SHA-256: a{64}/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Calibrate and apply' }));
    await waitFor(() => expect(createSemanticCalibration).toHaveBeenCalledWith(
      'project-1', expect.arrayContaining([expect.objectContaining({ expected_action: 'duplicate' })]), true,
    ));
  });
});
