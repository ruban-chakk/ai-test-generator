import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  bulkApproveTestCases,
  createFeedback,
  evaluateQuality,
  getKnowledgeDocuments,
  getProjectApprovalWorkflow,
  getQualityEvaluations,
  getRequirement,
  getTestCaseApprovalWorkflow,
  processFeedbackRevision,
  updateTestCase,
} from '../api';
import RequirementTestCases from './RequirementTestCases';

vi.mock('../api', () => ({
  approveTestCase: vi.fn(),
  bulkApproveTestCases: vi.fn(),
  createFeedback: vi.fn(),
  createKnowledgeDocument: vi.fn(),
  evaluateQuality: vi.fn(),
  getKnowledgeDocuments: vi.fn(),
  getProjectApprovalWorkflow: vi.fn(),
  getQualityEvaluations: vi.fn(),
  getRequirement: vi.fn(),
  getTestCaseApprovalWorkflow: vi.fn(),
  processFeedbackRevision: vi.fn(),
  rejectTestCase: vi.fn(),
  updateTestCase: vi.fn(),
  updateProjectApprovalWorkflow: vi.fn(),
}));

const workflow = {
  project_id: 'project-1',
  name: 'Governed review',
  version: 1,
  stages: [
    { name: 'Tester review', required_roles: ['tester'], minimum_approvals: 1 },
    { name: 'Lead review', required_roles: ['test_lead'], minimum_approvals: 1 },
  ],
  evaluation_required: true,
  minimum_evaluation_score: 80,
  allow_same_approver_multiple_stages: false,
};

describe('RequirementTestCases', () => {
  beforeEach(() => {
    vi.mocked(getRequirement).mockResolvedValue({
      id: 'requirement-1',
      project_id: 'project-1',
      title: 'Refund approval',
      description: 'Managers approve large refunds.',
      source: 'manual',
      status: 'generated',
      scenarios: [
        {
          id: 'scenario-1',
          title: 'Large refund',
          description: 'Verify manager authorization.',
          status: 'draft',
          version: 1,
          test_cases: [
            {
              id: 'case-1',
              title: 'Manager approval is required',
              description: 'Submit a refund above the configured threshold.',
              status: 'draft',
              version: 1,
              locked: false,
              repository_status: 'draft',
              steps: [
                { step_number: 1, action: 'Submit the large refund.', expected_result: 'Manager approval is requested.' },
              ],
            },
          ],
        },
      ],
    });
    vi.mocked(getProjectApprovalWorkflow).mockResolvedValue(workflow);
    vi.mocked(getKnowledgeDocuments).mockResolvedValue([]);
    vi.mocked(getQualityEvaluations).mockResolvedValue([]);
    vi.mocked(getTestCaseApprovalWorkflow).mockResolvedValue(null);
    vi.mocked(bulkApproveTestCases).mockResolvedValue({
      scope: 'requirement', requested_count: 1, processed_count: 1,
      approved_count: 1, in_review_count: 0, blocked_count: 0, failed_count: 0, items: [],
    });
    vi.mocked(createFeedback).mockResolvedValue({
      id: 'feedback-1', target_level: 'test_case', target_id: 'case-1', source: 'generated-test-review',
      feedback_type: 'revise', comment: 'Improve coverage.', created_by: 'admin', status: 'open', created_at: '2026-10-22T10:00:00Z',
    });
    vi.mocked(processFeedbackRevision).mockResolvedValue({
      id: 'revision-1', feedback_id: 'feedback-1', target_level: 'test_case', target_id: 'case-1',
      action: 'revise', status: 'completed', created_by: 'admin', created_at: '2026-10-22T10:00:00Z',
    });
  });

  it('offers suite, scenario, and test-case feedback at the review surface', async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={['/requirements/requirement-1/test-cases']}>
        <Routes>
          <Route
            path="/requirements/:id/test-cases"
            element={<RequirementTestCases user={{ id: 'user-1', username: 'admin', email: 'a@example.com', role: 'admin', active: true }} />}
          />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByRole('button', { name: 'Feedback on whole suite' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Scenario feedback' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /Manager approval is required/, expanded: false }));
    await waitFor(() => expect(getTestCaseApprovalWorkflow).toHaveBeenCalledWith('case-1'));
    expect(screen.getByRole('button', { name: 'Feedback to LLM' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Run evaluation' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Approve current stage' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Feedback to LLM' }));
    expect(screen.getByRole('dialog', { name: /Feedback on Manager approval is required/ })).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: /Include DeepEval evaluation data/ })).toBeDisabled();
  });

  it('supports bulk approval for the requirement and scenario scopes', async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={['/requirements/requirement-1/test-cases']}>
        <Routes><Route path="/requirements/:id/test-cases" element={<RequirementTestCases user={{ id: 'user-1', username: 'admin', email: 'a@example.com', role: 'admin', active: true }} />} /></Routes>
      </MemoryRouter>,
    );

    await user.click(await screen.findByRole('button', { name: 'Approve all test cases' }));
    await waitFor(() => expect(bulkApproveTestCases).toHaveBeenCalledWith('requirement-1', expect.objectContaining({ scope: 'requirement', approved_by: 'admin' })));

    await user.click(screen.getByRole('button', { name: /Approve scenario cases/ }));
    await waitFor(() => expect(bulkApproveTestCases).toHaveBeenCalledWith('requirement-1', expect.objectContaining({ scope: 'scenario', scenario_id: 'scenario-1' })));
  });

  it('explains deterministic-only evaluations and can replace them with DeepEval evidence', async () => {
    const user = userEvent.setup();
    const deterministicEvaluation = {
      id: 'evaluation-1', target_level: 'test_case', target_id: 'case-1', score: 100,
      status: 'passed', metrics: { evaluation_mode: 'deterministic', guardrail_score: 100 },
      issues: [], evaluated_by: 'admin', created_at: '2026-10-22T10:00:00Z',
    };
    const deepEvaluation = {
      ...deterministicEvaluation,
      id: 'evaluation-2', score: 92,
      metrics: {
        evaluation_mode: 'deterministic_and_llm_judge', overall_deepeval_status: 'green',
        judge_summary: 'The test case is grounded and executable.',
        deepeval_metrics: [{ name: 'grounding', score: 92, weight: 1, weighted_score: 92, status: 'green', justification: 'All assertions are grounded.' }],
      },
    };
    vi.mocked(getQualityEvaluations).mockResolvedValue([deterministicEvaluation]);
    vi.mocked(evaluateQuality).mockResolvedValue(deepEvaluation);

    render(
      <MemoryRouter initialEntries={['/requirements/requirement-1/test-cases']}>
        <Routes><Route path="/requirements/:id/test-cases" element={<RequirementTestCases user={{ id: 'user-1', username: 'admin', email: 'a@example.com', role: 'admin', active: true }} />} /></Routes>
      </MemoryRouter>,
    );

    await user.click(await screen.findByRole('button', { name: /Manager approval is required/, expanded: false }));
    const indicator = await screen.findByRole('button', { name: /View DeepEval metrics.*100 out of 100/ });
    await user.click(indicator);
    expect(screen.getByText(/used deterministic validation only because LLM-as-judge was disabled/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Run DeepEval now' }));
    await waitFor(() => expect(evaluateQuality).toHaveBeenCalledWith('test_case', 'case-1'));
    expect(await screen.findByText('All assertions are grounded.')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Use DeepEval feedback to revise' }));
    expect(screen.getByRole('dialog', { name: /Feedback on Manager approval is required/ })).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: /Include DeepEval evaluation data/ })).toBeChecked();
  });

  it('does not attach DeepEval data when the reviewer unchecks the explicit opt-in', async () => {
    const user = userEvent.setup();
    const deepEvaluation = {
      id: 'evaluation-2', target_level: 'test_case', target_id: 'case-1', score: 72,
      status: 'failed', metrics: {
        evaluation_mode: 'deterministic_and_llm_judge', overall_deepeval_status: 'amber',
        deepeval_metrics: [{ name: 'completeness', score: 65, weight: 1, weighted_score: 65, status: 'amber', justification: 'A path is missing.' }],
      }, issues: [], evaluated_by: 'admin', created_at: '2026-10-22T10:00:00Z',
    };
    vi.mocked(getQualityEvaluations).mockResolvedValue([deepEvaluation]);

    render(
      <MemoryRouter initialEntries={['/requirements/requirement-1/test-cases']}>
        <Routes><Route path="/requirements/:id/test-cases" element={<RequirementTestCases user={{ id: 'user-1', username: 'admin', email: 'a@example.com', role: 'admin', active: true }} />} /></Routes>
      </MemoryRouter>,
    );
    await user.click(await screen.findByRole('button', { name: /Manager approval is required/, expanded: false }));
    await user.click(await screen.findByRole('button', { name: /View DeepEval metrics/ }));
    await user.click(screen.getByRole('button', { name: 'Use DeepEval feedback to revise' }));
    await user.click(screen.getByRole('checkbox', { name: /Include DeepEval evaluation data/ }));
    await user.click(screen.getByRole('button', { name: 'Submit to LLM' }));

    await waitFor(() => expect(createFeedback).toHaveBeenCalled());
    expect(createFeedback).toHaveBeenCalledWith(expect.objectContaining({
      source: 'generated-test-review', quality_evaluation_id: undefined,
    }));
  });

  it('allows a reviewer to manually edit every field and queues a new draft version', async () => {
    const user = userEvent.setup();
    vi.mocked(updateTestCase).mockResolvedValue({
      id: 'case-1', title: 'Updated manager approval', description: 'Updated test case description.', status: 'draft',
      version: 2, locked: false, repository_status: 'draft', steps: [{ step_number: 1, action: 'Submit an updated refund.', expected_result: 'Approval is requested.' }],
    });
    render(
      <MemoryRouter initialEntries={['/requirements/requirement-1/test-cases']}>
        <Routes><Route path="/requirements/:id/test-cases" element={<RequirementTestCases user={{ id: 'user-1', username: 'admin', email: 'a@example.com', role: 'admin', active: true }} />} /></Routes>
      </MemoryRouter>,
    );
    await user.click(await screen.findByRole('button', { name: /Manager approval is required/, expanded: false }));
    await user.click(screen.getByRole('button', { name: 'Edit test case' }));
    const title = screen.getByRole('textbox', { name: 'Title' });
    await user.clear(title);
    await user.type(title, 'Updated manager approval');
    await user.click(screen.getByRole('button', { name: 'Save new draft version' }));
    await waitFor(() => expect(updateTestCase).toHaveBeenCalledWith('case-1', expect.objectContaining({
      expected_version: 1, title: 'Updated manager approval',
    })));
  });
});
