import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  createBulkOperation,
  getRequirements,
} from '../api';
import RequirementDashboard from './RequirementDashboard';

vi.mock('../api', () => ({
  createBulkOperation: vi.fn(),
  generateRequirementDraft: vi.fn(),
  getRequirementImpact: vi.fn(),
  getRequirements: vi.fn(),
}));

const project = { id: 'project-1', name: 'Refunds', status: 'active', description: 'Refund project', requirement_count: 2, test_case_count: 0 };
const requirements = [
  { id: 'requirement-1', project_id: 'project-1', title: 'Large refund approval', description: 'Manager approval.', source: 'manual', status: 'draft' },
  { id: 'requirement-2', project_id: 'project-1', title: 'Refund audit trail', description: 'Record approval history.', source: 'jira', status: 'generated' },
];

describe('RequirementDashboard bulk actions', () => {
  beforeEach(() => {
    vi.mocked(getRequirements).mockResolvedValue(requirements);
    vi.mocked(createBulkOperation).mockImplementation(async (_projectId, operationType, requirementIds) => ({
      id: 'batch-12345678', project_id: 'project-1', operation_type: operationType, status: 'queued',
      requirement_ids: requirementIds, total_count: requirementIds.length, completed_count: 0, failed_count: 0,
      result: { items: [] }, requested_by: 'admin', created_at: '2026-10-25T10:00:00Z', updated_at: '2026-10-25T10:00:00Z',
    }));
  });

  function renderPage() {
    return render(
      <MemoryRouter initialEntries={['/requirements']}>
        <RequirementDashboard selectedProject={project} />
      </MemoryRouter>,
    );
  }

  it('selects all visible requirements and bulk generates test cases', async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByText('Large refund approval');
    await user.click(screen.getByRole('button', { name: 'Select all' }));
    expect(screen.getByText('2 selected')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Generate test cases (2)' }));

    await waitFor(() => {
      expect(createBulkOperation).toHaveBeenCalledWith('project-1', 'generate_test_cases', ['requirement-1', 'requirement-2']);
    });
    expect(await screen.findByText(/test-case generation queued as batch/)).toBeInTheDocument();
  });

  it('runs impact analysis for selected requirements and supports clearing selection', async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByText('Refund audit trail');
    await user.click(screen.getByRole('checkbox', { name: 'Select Large refund approval' }));
    await user.click(screen.getByRole('checkbox', { name: 'Select Refund audit trail' }));
    await user.click(screen.getByRole('button', { name: 'Run impact analysis (2)' }));

    await waitFor(() => {
      expect(createBulkOperation).toHaveBeenCalledWith('project-1', 'impact_analysis', ['requirement-1', 'requirement-2']);
    });
    expect(await screen.findByText(/impact analysis queued as batch/)).toBeInTheDocument();
    expect(screen.getByText('0 selected')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Select all' }));
    await user.click(screen.getByRole('button', { name: 'Clear selection' }));
    expect(screen.getByText('0 selected')).toBeInTheDocument();
  });
});
