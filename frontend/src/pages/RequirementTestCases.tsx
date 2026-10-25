import { FormEvent, useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  approveTestCase,
  bulkApproveTestCases,
  ApprovalWorkflowRun,
  AuthenticatedUser,
  createFeedback,
  evaluateQuality,
  getQualityEvaluations,
  getProjectApprovalWorkflow,
  getRequirement,
  getTestCaseApprovalWorkflow,
  processFeedbackRevision,
  rejectTestCase,
  RequirementDetail,
  QualityEvaluationSummary,
  TestCaseSummary,
  updateTestCase,
} from '../api';

type FeedbackTarget = {
  level: 'requirement' | 'scenario' | 'test_case';
  id: string;
  label: string;
  availableQualityEvaluationId?: string;
};

type TestCaseEditDraft = {
  id: string;
  expected_version: number;
  title: string;
  description: string;
  prerequisite: string;
  priority: string;
  severity: string;
  category: string;
  type: string;
  steps: { step_number: number; action: string; expected_result: string }[];
};

export default function RequirementTestCases({ user }: { user: AuthenticatedUser }) {
  const { id } = useParams();
  const navigate = useNavigate();
  const [requirement, setRequirement] = useState<RequirementDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [expandedScenarios, setExpandedScenarios] = useState<Set<string>>(new Set());
  const [expandedTestCases, setExpandedTestCases] = useState<Set<string>>(new Set());
  const [workflow, setWorkflow] = useState<Awaited<ReturnType<typeof getProjectApprovalWorkflow>> | null>(null);
  const [workflowRuns, setWorkflowRuns] = useState<Record<string, ApprovalWorkflowRun | null>>({});
  const [evaluations, setEvaluations] = useState<Record<string, QualityEvaluationSummary | null>>({});
  const [aggregateEvaluations, setAggregateEvaluations] = useState<Record<string, QualityEvaluationSummary | null>>({});
  const [selectedEvaluation, setSelectedEvaluation] = useState<QualityEvaluationSummary | null>(null);
  const [busyCase, setBusyCase] = useState<string | null>(null);
  const [busyEvaluationTarget, setBusyEvaluationTarget] = useState<string | null>(null);
  const [approvalNotes, setApprovalNotes] = useState<Record<string, string>>({});
  const [feedbackTarget, setFeedbackTarget] = useState<FeedbackTarget | null>(null);
  const [feedbackType, setFeedbackType] = useState('revise');
  const [feedbackComment, setFeedbackComment] = useState('');
  const [feedbackSaving, setFeedbackSaving] = useState(false);
  const [feedbackIncludeEvaluation, setFeedbackIncludeEvaluation] = useState(false);
  const [editDraft, setEditDraft] = useState<TestCaseEditDraft | null>(null);
  const [editSaving, setEditSaving] = useState(false);
  const [selectedTestCases, setSelectedTestCases] = useState<Set<string>>(new Set());
  const [busyBulkScope, setBusyBulkScope] = useState<string | null>(null);

  async function loadRequirement() {
    if (!id) return;
    const data = await getRequirement(id);
    setRequirement(data);
    setExpandedScenarios((current) =>
      current.size ? current : new Set(data.scenarios?.map((scenario) => scenario.id) ?? []),
    );
    if (data.project_id) setWorkflow(await getProjectApprovalWorkflow(data.project_id));
    const targets = [
      { level: 'requirement' as const, id: data.id },
      ...(data.scenarios ?? []).map((scenario) => ({ level: 'scenario' as const, id: scenario.id })),
    ];
    const histories = await Promise.all(targets.map((target) => getQualityEvaluations(target.level, target.id)));
    setAggregateEvaluations((current) => Object.fromEntries(
      targets.map((target, index) => [`${target.level}:${target.id}`, histories[index][0] ?? null]),
    ));
  }

  useEffect(() => {
    if (!id) {
      setError('Requirement ID is missing');
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    loadRequirement()
      .catch((err) => setError(err instanceof Error ? err.message : 'Unable to load generated test cases'))
      .finally(() => setLoading(false));
  }, [id]);

  const toggleScenario = (scenarioId: string) => {
    setExpandedScenarios((current) => {
      const next = new Set(current);
      next.has(scenarioId) ? next.delete(scenarioId) : next.add(scenarioId);
      return next;
    });
  };

  const toggleTestCase = async (testCaseId: string) => {
    const opening = !expandedTestCases.has(testCaseId);
    setExpandedTestCases((current) => {
      const next = new Set(current);
      next.has(testCaseId) ? next.delete(testCaseId) : next.add(testCaseId);
      return next;
    });
    if (opening) {
      try {
        const [run, evaluationHistory] = await Promise.all([
          getTestCaseApprovalWorkflow(testCaseId),
          getQualityEvaluations('test_case', testCaseId),
        ]);
        setWorkflowRuns((current) => ({ ...current, [testCaseId]: run }));
        setEvaluations((current) => ({ ...current, [testCaseId]: evaluationHistory[0] ?? null }));
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unable to load approval workflow');
      }
    }
  };

  async function refreshCaseWorkflow(testCaseId: string) {
    const run = await getTestCaseApprovalWorkflow(testCaseId);
    setWorkflowRuns((current) => ({ ...current, [testCaseId]: run }));
  }

  async function handleEvaluate(testCaseId: string) {
    await handleEvaluateTarget('test_case', testCaseId);
  }

  async function handleEvaluateTarget(level: 'requirement' | 'scenario' | 'test_case', targetId: string) {
    const busyKey = `${level}:${targetId}`;
    try {
      setBusyEvaluationTarget(busyKey);
      setError(null);
      setNotice(null);
      const result = await evaluateQuality(level, targetId);
      if (level === 'test_case') {
        setEvaluations((current) => ({ ...current, [targetId]: result }));
        setSelectedEvaluation((current) => current?.target_id === targetId ? result : current);
        await refreshCaseWorkflow(targetId);
      } else {
        setAggregateEvaluations((current) => ({ ...current, [busyKey]: result }));
      }
      setNotice(`Evaluation ${result.status}: ${result.score}/100.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : `Unable to evaluate ${level}`);
    } finally {
      setBusyEvaluationTarget(null);
    }
  }

  const selectedDeepEvalMetrics = selectedEvaluation && Array.isArray(selectedEvaluation.metrics.deepeval_metrics)
    ? selectedEvaluation.metrics.deepeval_metrics as { name: string; score: number; weight: number; weighted_score: number; normalized_score?: number; direction?: string; status: string; justification: string }[]
    : null;
  const selectedEvaluationMode = selectedEvaluation?.metrics.evaluation_mode;

  function openFeedback(target: Omit<FeedbackTarget, 'availableQualityEvaluationId'>, evaluationId?: string) {
    setFeedbackTarget({ ...target, availableQualityEvaluationId: evaluationId });
    setFeedbackType('revise');
    setFeedbackComment('');
    setFeedbackIncludeEvaluation(false);
  }

  function openDeepEvalFeedback() {
    if (!selectedEvaluation || !selectedDeepEvalMetrics) return;
    const testCase = requirement?.scenarios?.flatMap((scenario) => scenario.test_cases ?? [])
      .find((item) => item.id === selectedEvaluation.target_id);
    setFeedbackTarget({
      level: 'test_case', id: selectedEvaluation.target_id,
      label: testCase?.title ?? 'evaluated test case', availableQualityEvaluationId: selectedEvaluation.id,
    });
    setFeedbackType('revise');
    setFeedbackIncludeEvaluation(true);
    setFeedbackComment('Revise this test case to improve its quality and coverage.');
    setSelectedEvaluation(null);
  }

  function openEdit(testCase: TestCaseSummary) {
    setEditDraft({
      id: testCase.id,
      expected_version: testCase.version,
      title: testCase.title,
      description: testCase.description,
      prerequisite: testCase.prerequisite ?? '',
      priority: testCase.priority ?? '',
      severity: testCase.severity ?? '',
      category: testCase.category ?? '',
      type: testCase.type ?? '',
      steps: (testCase.steps ?? []).slice().sort((a, b) => a.step_number - b.step_number)
        .map((step, index) => ({ ...step, step_number: index + 1 })),
    });
  }

  function moveEditStep(index: number, direction: -1 | 1) {
    setEditDraft((current) => {
      if (!current) return current;
      const nextIndex = index + direction;
      if (nextIndex < 0 || nextIndex >= current.steps.length) return current;
      const steps = current.steps.slice();
      [steps[index], steps[nextIndex]] = [steps[nextIndex], steps[index]];
      return { ...current, steps: steps.map((step, stepIndex) => ({ ...step, step_number: stepIndex + 1 })) };
    });
  }

  async function handleEdit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editDraft) return;
    try {
      setEditSaving(true);
      setError(null);
      await updateTestCase(editDraft.id, {
        expected_version: editDraft.expected_version,
        title: editDraft.title.trim(),
        description: editDraft.description.trim(),
        prerequisite: editDraft.prerequisite.trim() || undefined,
        priority: editDraft.priority.trim() || undefined,
        severity: editDraft.severity.trim() || undefined,
        category: editDraft.category.trim() || undefined,
        type: editDraft.type.trim() || undefined,
        steps: editDraft.steps.map((step, index) => ({
          step_number: index + 1,
          action: step.action.trim(),
          expected_result: step.expected_result.trim(),
        })),
      });
      setEvaluations((current) => ({ ...current, [editDraft.id]: null }));
      setWorkflowRuns((current) => ({ ...current, [editDraft.id]: null }));
      setEditDraft(null);
      await loadRequirement();
      setNotice('Test case saved as a new draft version. DeepEval evaluation has been queued automatically.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to update test case');
    } finally {
      setEditSaving(false);
    }
  }

  async function handleDecision(testCaseId: string, decision: 'approve' | 'reject') {
    try {
      setBusyCase(testCaseId);
      setError(null);
      setNotice(null);
      const payload = { approved_by: user.username, notes: approvalNotes[testCaseId] || undefined };
      if (decision === 'approve') await approveTestCase(testCaseId, payload);
      else await rejectTestCase(testCaseId, payload);
      await Promise.all([loadRequirement(), refreshCaseWorkflow(testCaseId)]);
      setNotice(decision === 'approve' ? 'Approval decision recorded.' : 'Changes requested.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to record approval decision');
    } finally {
      setBusyCase(null);
    }
  }

  function toggleSelectedTestCase(testCaseId: string) {
    setSelectedTestCases((current) => {
      const next = new Set(current);
      if (next.has(testCaseId)) next.delete(testCaseId);
      else next.add(testCaseId);
      return next;
    });
  }

  async function handleBulkApprove(
    scope: 'requirement' | 'scenario' | 'test_case',
    scenarioId?: string,
    testCaseIds?: string[],
  ) {
    if (!requirement) return;
    const busyKey = scenarioId ? `scenario:${scenarioId}` : scope;
    try {
      setBusyBulkScope(busyKey);
      setError(null);
      setNotice(null);
      const result = await bulkApproveTestCases(requirement.id, {
        scope,
        scenario_id: scenarioId,
        test_case_ids: testCaseIds,
        approved_by: user.username,
        notes: scope === 'requirement' ? 'Bulk approval from generated test review' : 'Bulk approval from scenario review',
      });
      setSelectedTestCases(new Set());
      await loadRequirement();
      const blocked = result.blocked_count + result.failed_count;
      setNotice(
        `${result.processed_count} case${result.processed_count === 1 ? '' : 's'} processed: ` +
        `${result.approved_count} fully approved, ${result.in_review_count} in review${blocked ? `, ${blocked} blocked` : ''}.`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to bulk approve test cases');
    } finally {
      setBusyBulkScope(null);
    }
  }

  async function handleFeedback(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!feedbackTarget) return;
    try {
      setFeedbackSaving(true);
      setError(null);
      const feedback = await createFeedback({
        target_level: feedbackTarget.level,
        target_id: feedbackTarget.id,
        source: feedbackIncludeEvaluation ? 'deepeval-review' : 'generated-test-review',
        feedback_type: feedbackType,
        comment: feedbackComment.trim(),
        created_by: user.username,
        quality_evaluation_id: feedbackIncludeEvaluation
          ? feedbackTarget.availableQualityEvaluationId
          : undefined,
      });
      if (feedbackType === 'revise' || feedbackType === 'generate_new') {
        await processFeedbackRevision({
          feedback_id: feedback.id,
          action: feedbackType,
          created_by: user.username,
          notes: `Processed from ${feedbackTarget.label}`,
        });
      }
      const refreshedTarget = { level: feedbackTarget.level, id: feedbackTarget.id };
      setFeedbackTarget(null);
      setFeedbackComment('');
      setFeedbackIncludeEvaluation(false);
      setNotice(feedbackType === 'revise' || feedbackType === 'generate_new'
        ? 'Feedback was applied to a new draft version. DeepEval evaluation has been queued automatically.'
        : 'Feedback was stored and indexed for RAG.');
      await loadRequirement();
      const refreshedHistory = await getQualityEvaluations(refreshedTarget.level, refreshedTarget.id);
      if (refreshedTarget.level === 'test_case') {
        setEvaluations((current) => ({ ...current, [refreshedTarget.id]: refreshedHistory[0] ?? null }));
      } else {
        setAggregateEvaluations((current) => ({ ...current, [`${refreshedTarget.level}:${refreshedTarget.id}`]: refreshedHistory[0] ?? null }));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to process feedback');
    } finally {
      setFeedbackSaving(false);
    }
  }

  return (
    <main className="page-container">
      <header className="page-header">
        <div>
          <p className="eyebrow">Generated test review</p>
          <h1>{requirement?.title ?? 'Generated Test Cases'}</h1>
          {requirement ? <span className="header-subtitle">Requirement ID: {requirement.id}</span> : null}
          {requirement && aggregateEvaluations[`requirement:${requirement.id}`] ? (
            <span className="status-pill evaluation-score">Requirement evaluation: {aggregateEvaluations[`requirement:${requirement.id}`]?.score}/100 · {aggregateEvaluations[`requirement:${requirement.id}`]?.status} · coverage {String(aggregateEvaluations[`requirement:${requirement.id}`]?.metrics.coverage_score ?? '—')}/100</span>
          ) : null}
        </div>
        <div className="header-actions">
          {requirement ? (
            <>
              <button className="secondary-button" type="button" onClick={() => openFeedback({ level: 'requirement', id: requirement.id, label: 'whole generated suite' }, aggregateEvaluations[`requirement:${requirement.id}`]?.id)}>
                Feedback on whole suite
              </button>
              <button className="primary-button" type="button" onClick={() => handleEvaluateTarget('requirement', requirement.id)} disabled={busyEvaluationTarget === `requirement:${requirement.id}`}>
                {busyEvaluationTarget === `requirement:${requirement.id}` ? 'Evaluating suite...' : 'Run suite evaluation'}
              </button>
              <button className="primary-button" type="button" onClick={() => handleBulkApprove('requirement')} disabled={busyBulkScope === 'requirement'}>
                {busyBulkScope === 'requirement' ? 'Approving suite...' : 'Approve all test cases'}
              </button>
            </>
          ) : null}
          <button className="secondary-button" type="button" onClick={() => navigate('/requirements')}>Requirements</button>
          {requirement ? <Link className="primary-button" to={`/requirements/${requirement.id}`}>View Requirement</Link> : null}
        </div>
      </header>

      {error ? <div className="status-message status-error" role="alert">{error}</div> : null}
      {notice ? <div className="status-message" role="status">{notice}</div> : null}

      {loading ? <div className="status-message">Loading generated test cases...</div> : requirement ? (
        <>
          <section className="testcase-browser" aria-label="Generated test cases by scenario">
            {requirement.scenarios?.length ? requirement.scenarios.map((scenario) => {
              const isScenarioExpanded = expandedScenarios.has(scenario.id);
              const testCases = scenario.test_cases ?? [];
              return (
                <article key={scenario.id} className="collapsible-card">
                  <div className="collapsible-header-row">
                    <button className="collapsible-header" type="button" aria-expanded={isScenarioExpanded} onClick={() => toggleScenario(scenario.id)}>
                      <span className="collapse-indicator">{isScenarioExpanded ? '-' : '+'}</span>
                      <span><strong>{scenario.title}</strong><span className="table-description">{scenario.description} · {testCases.length} test case{testCases.length === 1 ? '' : 's'}</span></span>
                      {aggregateEvaluations[`scenario:${scenario.id}`] ? <span className="status-pill evaluation-score">Evaluation {aggregateEvaluations[`scenario:${scenario.id}`]?.score}/100 · {aggregateEvaluations[`scenario:${scenario.id}`]?.status}</span> : null}
                    </button>
                    <div className="detail-actions">
                      <button className="secondary-button compact-button" type="button" onClick={() => openFeedback({ level: 'scenario', id: scenario.id, label: scenario.title }, aggregateEvaluations[`scenario:${scenario.id}`]?.id)}>Scenario feedback</button>
                      <button className="secondary-button compact-button" type="button" onClick={() => handleEvaluateTarget('scenario', scenario.id)} disabled={busyEvaluationTarget === `scenario:${scenario.id}`}>
                        {busyEvaluationTarget === `scenario:${scenario.id}` ? 'Evaluating...' : 'Run scenario evaluation'}
                      </button>
                      <button className="primary-button compact-button" type="button" onClick={() => handleBulkApprove('scenario', scenario.id)} disabled={busyBulkScope === `scenario:${scenario.id}`}>
                        {busyBulkScope === `scenario:${scenario.id}` ? 'Approving...' : 'Approve scenario cases'}
                      </button>
                      {testCases.some((item) => selectedTestCases.has(item.id)) ? <button className="secondary-button compact-button" type="button" onClick={() => handleBulkApprove('test_case', undefined, testCases.filter((item) => selectedTestCases.has(item.id)).map((item) => item.id))} disabled={busyBulkScope === 'test_case'}>Approve selected ({testCases.filter((item) => selectedTestCases.has(item.id)).length})</button> : null}
                    </div>
                  </div>

                  {isScenarioExpanded ? (
                    <div className="collapsible-body">
                      {testCases.length ? <div className="testcase-list">{testCases.map((testCase) => {
                        const isExpanded = expandedTestCases.has(testCase.id);
                        const steps = testCase.steps ?? [];
                        const run = workflowRuns[testCase.id];
                        const evaluation = evaluations[testCase.id];
                        const evaluationStatus = String(evaluation?.metrics.overall_deepeval_status ?? (evaluation ? evaluation.score >= 80 ? 'green' : evaluation.score >= 60 ? 'amber' : 'red' : 'pending'));
                        const policy = run?.policy ?? workflow;
                        const currentStage = run && policy ? policy.stages[run.current_stage] : undefined;
                        return (
                          <article key={testCase.id} className="testcase-item">
                            <label className="testcase-select">
                              <input type="checkbox" checked={selectedTestCases.has(testCase.id)} onChange={() => toggleSelectedTestCase(testCase.id)} aria-label={`Select ${testCase.title} for bulk approval`} />
                            </label>
                            <button className="testcase-summary" type="button" aria-expanded={isExpanded} onClick={() => toggleTestCase(testCase.id)}>
                              <span className="collapse-indicator">{isExpanded ? '-' : '+'}</span>
                              <span><span className="testcase-id">Test ID: {testCase.id}</span><strong>{testCase.title}</strong><span className="table-description">{testCase.description}</span></span>
                              <span className="status-pill">{testCase.status}</span>
                            </button>
                            <button className={`deepeval-indicator deepeval-${evaluationStatus}`} type="button" aria-label={evaluation ? `View DeepEval metrics for ${testCase.title}: ${evaluation.score} out of 100` : `DeepEval metrics pending for ${testCase.title}`} disabled={!evaluation} onClick={() => evaluation && setSelectedEvaluation(evaluation)}><span aria-hidden="true">◆</span><small>{evaluation ? evaluation.score : '—'}</small></button>

                            {isExpanded ? (
                              <div className="testcase-review-panel">
                                <div className="table-scroll testcase-steps">
                                  {steps.length ? (
                                    <table className="data-table steps-table">
                                      <thead><tr><th scope="col">Step No</th><th scope="col">Test Steps</th><th scope="col">Expected Results</th></tr></thead>
                                      <tbody>{steps.slice().sort((a, b) => a.step_number - b.step_number).map((step) => <tr key={step.step_number}><td>{step.step_number}</td><td>{step.action}</td><td>{step.expected_result}</td></tr>)}</tbody>
                                    </table>
                                  ) : <div className="status-message">No steps available for this test case.</div>}
                                </div>

                                <div className="governance-strip review-governance">
                                  <div>
                                    <span className="detail-label">Evaluation and approval</span>
                                    <strong>{run ? `${run.status} · stage ${Math.min(run.current_stage + 1, policy?.stages.length ?? 1)} of ${policy?.stages.length ?? 1}` : testCase.status === 'approved' ? 'Approved before staged workflow' : 'Not evaluated'}</strong>
                                    {currentStage ? <span className="table-description">Next: {currentStage.name} ({currentStage.required_roles.join(', ')})</span> : null}
                                  </div>
                                  <button className="secondary-button" type="button" disabled={busyCase === testCase.id} onClick={() => handleEvaluate(testCase.id)}>{busyCase === testCase.id ? 'Working...' : 'Run evaluation'}</button>
                                  <button className="secondary-button" type="button" onClick={() => openFeedback({ level: 'test_case', id: testCase.id, label: testCase.title }, evaluation?.id)}>Feedback to LLM</button>
                                  <button className="secondary-button" type="button" onClick={() => openEdit(testCase)}>Edit test case</button>
                                </div>

                                {run?.decisions.length ? <ol className="workflow-timeline">{run.decisions.map((decision) => <li key={decision.id}><strong>{decision.stage_name}</strong>: {decision.decision} by {decision.decided_by} ({decision.decided_role})</li>)}</ol> : null}
                                <label>Approval notes<input value={approvalNotes[testCase.id] ?? ''} onChange={(event) => setApprovalNotes((current) => ({ ...current, [testCase.id]: event.target.value }))} /></label>
                                <div className="detail-actions">
                                  <button className="primary-button" type="button" disabled={busyCase === testCase.id || run?.status === 'approved' || testCase.status === 'approved'} onClick={() => handleDecision(testCase.id, 'approve')}>Approve current stage</button>
                                  <button className="secondary-button" type="button" disabled={busyCase === testCase.id || run?.status === 'approved' || testCase.status === 'approved'} onClick={() => handleDecision(testCase.id, 'reject')}>Request changes</button>
                                </div>
                              </div>
                            ) : null}
                          </article>
                        );
                      })}</div> : <div className="status-message">No test cases generated for this scenario.</div>}
                    </div>
                  ) : null}
                </article>
              );
            }) : <div className="status-message">No test scenarios available for this requirement.</div>}
          </section>

          <div className="review-settings-link"><span>Approval workflow, RAG documents, and calibration are managed at project level.</span><Link className="secondary-button" to="/project-settings">Open project settings</Link></div>
        </>
      ) : <div className="status-message">Requirement not found.</div>}

      {feedbackTarget ? (
        <div className="modal-backdrop" role="presentation">
          <div className="modal-panel" role="dialog" aria-modal="true" aria-labelledby="feedback-title">
            <div className="modal-header">
              <div><p className="eyebrow">RAG feedback</p><h2 id="feedback-title">Feedback on {feedbackTarget.label}</h2></div>
              <button className="secondary-button" type="button" onClick={() => setFeedbackTarget(null)}>Close</button>
            </div>
            <p>The LLM receives the exact target, its requirement context, and relevant project documents and approved tests.</p>
            <form className="feedback-form" onSubmit={handleFeedback}>
              <label>Action<select value={feedbackType} onChange={(event) => setFeedbackType(event.target.value)}><option value="revise">Revise this content</option><option value="generate_new">Generate an additional alternative</option><option value="accept">Record as accepted</option><option value="reject">Record as rejected</option></select></label>
              <label>Feedback<textarea rows={6} value={feedbackComment} onChange={(event) => setFeedbackComment(event.target.value)} required autoFocus /></label>
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={feedbackIncludeEvaluation}
                  disabled={!feedbackTarget.availableQualityEvaluationId}
                  onChange={(event) => setFeedbackIncludeEvaluation(event.target.checked)}
                />
                <span>Include DeepEval evaluation data with this feedback
                  <small>{feedbackTarget.availableQualityEvaluationId ? ' The linked metric scores, justifications, and issues will be sent to the LLM.' : ' Run evaluation first to enable this option.'}</small>
                </span>
              </label>
              <button className="primary-button" type="submit" disabled={feedbackSaving}>{feedbackSaving ? 'Applying feedback...' : 'Submit to LLM'}</button>
            </form>
          </div>
        </div>
      ) : null}

      {editDraft ? (
        <div className="modal-backdrop" role="presentation">
          <div className="modal-panel test-case-edit-modal" role="dialog" aria-modal="true" aria-labelledby="edit-test-case-title">
            <div className="modal-header">
              <div><p className="eyebrow">Manual test design</p><h2 id="edit-test-case-title">Edit test case</h2></div>
              <button className="secondary-button" type="button" onClick={() => setEditDraft(null)}>Close</button>
            </div>
            <p>Saving creates a new draft version, invalidates prior approval for the mutable case, and queues DeepEval automatically. Approved snapshots remain unchanged.</p>
            <form className="feedback-form" onSubmit={handleEdit}>
              <label>Title<input value={editDraft.title} minLength={5} required onChange={(event) => setEditDraft({ ...editDraft, title: event.target.value })} autoFocus /></label>
              <label>Description<textarea rows={4} value={editDraft.description} minLength={12} required onChange={(event) => setEditDraft({ ...editDraft, description: event.target.value })} /></label>
              <label>Prerequisite<textarea rows={2} value={editDraft.prerequisite} onChange={(event) => setEditDraft({ ...editDraft, prerequisite: event.target.value })} /></label>
              <div className="edit-metadata-grid">
                {(['priority', 'severity', 'category', 'type'] as const).map((field) => (
                  <label key={field}>{field[0].toUpperCase() + field.slice(1)}<input value={editDraft[field]} onChange={(event) => setEditDraft({ ...editDraft, [field]: event.target.value })} /></label>
                ))}
              </div>
              <fieldset className="edit-steps-fieldset">
                <legend>Test steps</legend>
                {editDraft.steps.map((step, index) => (
                  <div className="edit-step-row" key={`${index}-${step.step_number}`}>
                    <strong>Step {index + 1}</strong>
                    <label>Action<textarea rows={2} required value={step.action} onChange={(event) => setEditDraft({ ...editDraft, steps: editDraft.steps.map((item, itemIndex) => itemIndex === index ? { ...item, action: event.target.value } : item) })} /></label>
                    <label>Expected result<textarea rows={2} required value={step.expected_result} onChange={(event) => setEditDraft({ ...editDraft, steps: editDraft.steps.map((item, itemIndex) => itemIndex === index ? { ...item, expected_result: event.target.value } : item) })} /></label>
                    <div className="edit-step-actions">
                      <button className="secondary-button compact-button" type="button" disabled={index === 0} onClick={() => moveEditStep(index, -1)}>Move up</button>
                      <button className="secondary-button compact-button" type="button" disabled={index === editDraft.steps.length - 1} onClick={() => moveEditStep(index, 1)}>Move down</button>
                      <button className="secondary-button compact-button" type="button" disabled={editDraft.steps.length === 1} onClick={() => setEditDraft({ ...editDraft, steps: editDraft.steps.filter((_, itemIndex) => itemIndex !== index).map((item, itemIndex) => ({ ...item, step_number: itemIndex + 1 })) })}>Remove step</button>
                    </div>
                  </div>
                ))}
                <button className="secondary-button" type="button" onClick={() => setEditDraft({ ...editDraft, steps: [...editDraft.steps, { step_number: editDraft.steps.length + 1, action: '', expected_result: '' }] })}>Add step</button>
              </fieldset>
              <div className="form-actions">
                <button className="secondary-button" type="button" onClick={() => setEditDraft(null)}>Cancel</button>
                <button className="primary-button" type="submit" disabled={editSaving}>{editSaving ? 'Saving…' : 'Save new draft version'}</button>
              </div>
            </form>
          </div>
        </div>
      ) : null}

      {selectedEvaluation ? (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setSelectedEvaluation(null); }}>
          <div className="modal-panel evaluation-modal" role="dialog" aria-modal="true" aria-labelledby="evaluation-title">
            <div className="modal-header"><div><p className="eyebrow">DeepEval evidence</p><h2 id="evaluation-title">Evaluation {selectedEvaluation.score}/100</h2></div><button className="secondary-button" type="button" onClick={() => setSelectedEvaluation(null)}>Close</button></div>
            <div className="evaluation-metrics-list">
              {selectedDeepEvalMetrics ? selectedDeepEvalMetrics.map((metric) => <article className={`evaluation-metric metric-${metric.status}`} key={metric.name}><div><span className="metric-signal" aria-hidden="true" /><strong>{metric.name.replace(/_/g, ' ')}</strong><span>{metric.score}{metric.name === 'hallucination_rate' ? '% rate' : '/100'} · weight {(metric.weight * 100).toFixed(0)}% · contribution {metric.weighted_score}</span></div><p>{metric.justification}</p></article>) : <div className="status-message"><p>{selectedEvaluationMode === 'deterministic' ? 'This evaluation used deterministic validation only because LLM-as-judge was disabled. Run it again to generate weighted DeepEval evidence.' : 'This legacy evaluation does not contain detailed DeepEval evidence.'}</p><button className="primary-button" type="button" disabled={busyCase === selectedEvaluation.target_id} onClick={() => handleEvaluate(selectedEvaluation.target_id)}>{busyCase === selectedEvaluation.target_id ? 'Evaluating…' : 'Run DeepEval now'}</button></div>}
              {typeof selectedEvaluation.metrics.judge_summary === 'string' ? <div className="evaluation-summary"><strong>Overall justification</strong><p>{selectedEvaluation.metrics.judge_summary}</p></div> : null}
              {selectedDeepEvalMetrics ? <div className="form-actions"><button className="primary-button" type="button" onClick={openDeepEvalFeedback}>Use DeepEval feedback to revise</button></div> : null}
            </div>
          </div>
        </div>
      ) : null}
    </main>
  );
}
