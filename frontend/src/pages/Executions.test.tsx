import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getExecutionCandidates, getTestExecutions, queueTestExecutions } from '../api';
import Executions from './Executions';

vi.mock('../api', () => ({
  getExecutionCandidates: vi.fn(),
  getTestExecutions: vi.fn(),
  queueTestExecutions: vi.fn(),
}));

const project = {
  id: 'project-1',
  name: 'Checkout',
  status: 'active',
  requirement_count: 1,
  test_case_count: 1,
};

describe('Executions', () => {
  beforeEach(() => {
    vi.mocked(getExecutionCandidates).mockResolvedValue([
      {
        id: 'case-1',
        title: 'Reject expired token',
        description: 'Expired tokens are rejected.',
        status: 'approved',
        version: 2,
        locked: true,
        repository_status: 'synced',
        steps: [{ step_number: 1, action: 'Open token', expected_result: 'Rejected' }],
      },
    ]);
    vi.mocked(getTestExecutions).mockResolvedValue([]);
    vi.mocked(queueTestExecutions).mockResolvedValue([]);
  });

  it('queues selected approved cases and refreshes history', async () => {
    const user = userEvent.setup();
    render(<Executions selectedProject={project} canExecute />);

    const candidate = await screen.findByText('Reject expired token');
    expect(candidate).toBeInTheDocument();
    await user.click(screen.getByRole('checkbox'));
    await user.click(screen.getByRole('button', { name: 'Run selected (1)' }));

    await waitFor(() => {
      expect(queueTestExecutions).toHaveBeenCalledWith('project-1', ['case-1'], 'staging');
      expect(getTestExecutions).toHaveBeenCalledTimes(2);
    });
  });

  it('allows reviewers to inspect history without queue controls', async () => {
    render(<Executions selectedProject={project} canExecute={false} />);
    await screen.findByText('Run history');
    expect(screen.queryByText('Queue approved cases')).not.toBeInTheDocument();
  });
});
