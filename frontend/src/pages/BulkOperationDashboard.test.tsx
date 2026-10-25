import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getBulkOperations } from '../api';
import BulkOperationDashboard from './BulkOperationDashboard';

vi.mock('../api', () => ({ getBulkOperations: vi.fn() }));

describe('BulkOperationDashboard', () => {
  beforeEach(() => {
    vi.mocked(getBulkOperations).mockResolvedValue([{
      id: 'job-1', project_id: 'project-1', operation_type: 'generate_test_cases', status: 'processing',
      requirement_ids: ['requirement-1'], total_count: 1, completed_count: 0, failed_count: 0,
      result: { items: [{ requirement_id: 'requirement-1', status: 'processing', message: null }] },
      requested_by: 'admin', created_at: '2026-10-25T10:00:00Z', updated_at: '2026-10-25T10:00:00Z',
    }]);
  });

  it('shows aggregate and per-requirement progress', async () => {
    render(<MemoryRouter><BulkOperationDashboard selectedProject={{ id: 'project-1', name: 'Refunds', status: 'active', requirement_count: 1, test_case_count: 0 }} /></MemoryRouter>);
    await waitFor(() => expect(screen.getAllByText('Test-case generation').length).toBeGreaterThan(0));
    expect(screen.getByText('Requirement item status')).toBeInTheDocument();
    expect(screen.getByText('requirement-1')).toBeInTheDocument();
    expect(screen.getAllByText('processing').length).toBeGreaterThan(0);
  });
});
