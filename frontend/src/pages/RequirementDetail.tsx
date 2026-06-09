import { FormEvent, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  approveRequirement,
  approveScenario,
  approveTestCase,
  createFeedback,
  createScenarioForRequirement,
  createTestCaseForScenario,
  getAudit,
  getApprovals,
  getFeedback,
  getTestCaseVersions,
  generateRequirementDraft,
  getRequirement,
  rejectRequirement,
  rejectScenario,
  rejectTestCase,
  ApprovalRecordSummary,
  AuditLogSummary,
  FeedbackSummary,
  RequirementDetail,
  TestCaseVersionSummary,
  ValidationResult,
  validateTarget,
} from '../api';

const defaultScenarioValues = {
  title: '',
  description: '',
  priority: 'medium',
  severity: 'major',
  category: 'functional',
  type: 'regression',
};

const defaultTestCaseValues = {
  title: '',
  description: '',
  prerequisite: '',
  priority: 'medium',
  severity: 'major',
  category: 'functional',
  type: 'regression',
};

export default function RequirementDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [requirement, setRequirement] = useState<RequirementDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [scenarioForm, setScenarioForm] = useState(defaultScenarioValues);
  const [scenarioSaving, setScenarioSaving] = useState(false);

  const [activeTestCaseScenarioId, setActiveTestCaseScenarioId] = useState<string | null>(null);
  const [testCaseForm, setTestCaseForm] = useState(defaultTestCaseValues);
  const [testCaseSaving, setTestCaseSaving] = useState(false);
  const [actionSaving, setActionSaving] = useState(false);

  const [feedbackTarget, setFeedbackTarget] = useState<{
    level: 'requirement' | 'scenario' | 'test_case';
    id: string;
  } | null>(null);
  const [feedbackType, setFeedbackType] = useState('revise');
  const [feedbackComment, setFeedbackComment] = useState('');
  const [feedbackCreatedBy, setFeedbackCreatedBy] = useState('system');
  const [feedbackSaving, setFeedbackSaving] = useState(false);
  const [feedbackList, setFeedbackList] = useState<FeedbackSummary[]>([]);
  const [approvalRecords, setApprovalRecords] = useState<ApprovalRecordSummary[]>([]);
  const [auditRecords, setAuditRecords] = useState<AuditLogSummary[]>([]);
  const [versionRecords, setVersionRecords] = useState<TestCaseVersionSummary[]>([]);
  const [validationResult, setValidationResult] = useState<ValidationResult | null>(null);
  const [validationSaving, setValidationSaving] = useState(false);

  useEffect(() => {
    if (!id) {
      setError('Requirement ID is missing');
      setLoading(false);
      return;
    }

    async function fetchRequirement() {
      try {
        setLoading(true);
        setError(null);
        const requirementId = id as string;
        const data = await getRequirement(requirementId);
        setRequirement(data);
        setFeedbackTarget({ level: 'requirement', id: requirementId });
        await refreshHistory(requirementId, 'requirement');
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unable to load requirement');
      } finally {
        setLoading(false);
      }
    }

    fetchRequirement();
  }, [id]);

  const refreshRequirement = async () => {
    if (!id) return;

    try {
      setLoading(true);
      setError(null);
      const data = await getRequirement(id);
      setRequirement(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to refresh requirement');
    } finally {
      setLoading(false);
    }
  };

  const refreshHistory = async (
    targetId: string,
    targetLevel: 'requirement' | 'scenario' | 'test_case',
  ) => {
    try {
      setError(null);
      const [feedbackData, approvalsData, auditData, versionData] = await Promise.all([
        getFeedback(targetLevel, targetId),
        getApprovals(targetLevel, targetId),
        getAudit(targetLevel, targetId),
        targetLevel === 'test_case' ? getTestCaseVersions(targetId) : Promise.resolve([]),
      ]);
      setFeedbackList(feedbackData);
      setApprovalRecords(approvalsData);
      setAuditRecords(auditData);
      setVersionRecords(versionData);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load review history');
    }
  };

  const handleSelectFeedbackTarget = (
    level: 'requirement' | 'scenario' | 'test_case',
    targetId: string,
  ) => {
    setFeedbackTarget({ level, id: targetId });
    setValidationResult(null);
    refreshHistory(targetId, level);
  };

  const handleValidateTarget = async () => {
    if (!feedbackTarget) {
      setError('Select a review target first');
      return;
    }

    try {
      setValidationSaving(true);
      setError(null);
      const result = await validateTarget(feedbackTarget.level, feedbackTarget.id);
      setValidationResult(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to validate target');
    } finally {
      setValidationSaving(false);
    }
  };

  const handleCreateFeedback = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!feedbackTarget) {
      setError('Select a feedback target first');
      return;
    }

    try {
      setFeedbackSaving(true);
      setError(null);
      await createFeedback({
        target_level: feedbackTarget.level,
        target_id: feedbackTarget.id,
        source: 'user',
        feedback_type: feedbackType,
        comment: feedbackComment,
        created_by: feedbackCreatedBy,
      });
      setFeedbackComment('');
      await refreshHistory(feedbackTarget.id, feedbackTarget.level);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to submit feedback');
    } finally {
      setFeedbackSaving(false);
    }
  };

  const handleGenerateDraft = async () => {
    if (!id) {
      setError('Requirement ID is missing');
      return;
    }

    try {
      setSaving(true);
      setError(null);
      const data = await generateRequirementDraft(id);
      setRequirement(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to generate draft');
    } finally {
      setSaving(false);
    }
  };

  const handleRequirementApproval = async (action: 'approve' | 'reject') => {
    if (!id) {
      setError('Requirement ID is missing');
      return;
    }

    try {
      setActionSaving(true);
      setError(null);
      if (action === 'approve') {
        await approveRequirement(id, { approved_by: 'system' });
      } else {
        await rejectRequirement(id, { approved_by: 'system' });
      }
      await refreshRequirement();
      await refreshHistory(id, 'requirement');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to update requirement');
    } finally {
      setActionSaving(false);
    }
  };

  const handleScenarioApproval = async (scenarioId: string, action: 'approve' | 'reject') => {
    try {
      setActionSaving(true);
      setError(null);
      if (action === 'approve') {
        await approveScenario(scenarioId, { approved_by: 'system' });
      } else {
        await rejectScenario(scenarioId, { approved_by: 'system' });
      }
      setFeedbackTarget({ level: 'scenario', id: scenarioId });
      await refreshRequirement();
      await refreshHistory(scenarioId, 'scenario');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to update scenario');
    } finally {
      setActionSaving(false);
    }
  };

  const handleTestCaseApproval = async (testCaseId: string, action: 'approve' | 'reject') => {
    try {
      setActionSaving(true);
      setError(null);
      if (action === 'approve') {
        await approveTestCase(testCaseId, { approved_by: 'system' });
      } else {
        await rejectTestCase(testCaseId, { approved_by: 'system' });
      }
      setFeedbackTarget({ level: 'test_case', id: testCaseId });
      await refreshRequirement();
      await refreshHistory(testCaseId, 'test_case');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to update test case');
    } finally {
      setActionSaving(false);
    }
  };

  const handleScenarioChange = (field: string, value: string) => {
    setScenarioForm((current) => ({ ...current, [field]: value }));
  };

  const handleCreateScenario = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    if (!id) {
      setError('Requirement ID is missing');
      return;
    }

    try {
      setScenarioSaving(true);
      setError(null);
      const newScenario = await createScenarioForRequirement(id, scenarioForm);
      setRequirement((current) =>
        current
          ? {
              ...current,
              scenarios: [...(current.scenarios ?? []), newScenario],
            }
          : current,
      );
      setScenarioForm(defaultScenarioValues);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to create scenario');
    } finally {
      setScenarioSaving(false);
    }
  };

  const handleTestCaseChange = (field: string, value: string) => {
    setTestCaseForm((current) => ({ ...current, [field]: value }));
  };

  const handleCreateTestCase = async (event: FormEvent<HTMLFormElement>, scenarioId: string) => {
    event.preventDefault();

    try {
      setTestCaseSaving(true);
      setError(null);
      const newTestCase = await createTestCaseForScenario(scenarioId, testCaseForm);
      setRequirement((current) =>
        current
          ? {
              ...current,
              scenarios: current.scenarios?.map((scenario) =>
                scenario.id === scenarioId
                  ? {
                      ...scenario,
                      test_cases: [...(scenario.test_cases ?? []), newTestCase],
                    }
                  : scenario,
              ),
            }
          : current,
      );
      setTestCaseForm(defaultTestCaseValues);
      setActiveTestCaseScenarioId(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to create test case');
    } finally {
      setTestCaseSaving(false);
    }
  };

  return (
    <main className="page-container">
      <header className="page-header">
        <div>
          <p className="eyebrow">Requirement detail</p>
          <h1>{requirement?.title ?? 'Requirement details'}</h1>
        </div>
        <button className="secondary-button" onClick={() => navigate('/requirements')}>
          Back to list
        </button>
      </header>

      {loading ? (
        <div className="status-message">Loading requirement...</div>
      ) : error ? (
        <div className="status-message status-error">{error}</div>
      ) : requirement ? (
        <section className="detail-grid">
          <div className="detail-panel">
            <div className="detail-row">
              <span className="detail-label">ID</span>
              <span>{requirement.id}</span>
            </div>
            <div className="detail-row">
              <span className="detail-label">External ID</span>
              <span>{requirement.external_id ?? '—'}</span>
            </div>
            <div className="detail-row">
              <span className="detail-label">Source</span>
              <span>{requirement.source}</span>
            </div>
            <div className="detail-row">
              <span className="detail-label">Status</span>
              <span>{requirement.status}</span>
            </div>
            <div className="detail-row">
              <span className="detail-label">Created</span>
              <span>{requirement.created_at ? new Date(requirement.created_at).toLocaleString() : '—'}</span>
            </div>
            <div className="detail-row">
              <span className="detail-label">Updated</span>
              <span>{requirement.updated_at ? new Date(requirement.updated_at).toLocaleString() : '—'}</span>
            </div>
            <div className="detail-row detail-actions">
              <button className="primary-button" onClick={handleGenerateDraft} disabled={saving || actionSaving}>
                {saving ? 'Generating…' : 'Generate Draft'}
              </button>
              <button
                className="secondary-button"
                type="button"
                onClick={() => handleRequirementApproval('approve')}
                disabled={actionSaving}
              >
                Approve Requirement
              </button>
              <button
                className="secondary-button"
                type="button"
                onClick={() => handleRequirementApproval('reject')}
                disabled={actionSaving}
              >
                Reject Requirement
              </button>
            </div>
          </div>

          <article className="detail-card">
            <h2>Description</h2>
            <p>{requirement.description}</p>
          </article>

          <article className="detail-card">
            <h2>Review history</h2>
            <div className="governance-strip">
              <div>
                <span className="detail-label">Selected target</span>
                <strong>
                  {feedbackTarget
                    ? `${feedbackTarget.level.replace('_', ' ')} · ${feedbackTarget.id}`
                    : 'No target selected'}
                </strong>
              </div>
              <button
                className="secondary-button"
                type="button"
                onClick={handleValidateTarget}
                disabled={validationSaving}
              >
                {validationSaving ? 'Validating...' : 'Run guardrails'}
              </button>
            </div>
            {validationResult ? (
              <div className={validationResult.valid ? 'validation-card valid' : 'validation-card invalid'}>
                <strong>{validationResult.valid ? 'Validation passed' : 'Validation needs attention'}</strong>
                {validationResult.issues.length ? (
                  <ul>
                    {validationResult.issues.map((issue) => (
                      <li key={`${issue.field}-${issue.message}`}>
                        {issue.field}: {issue.message}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
            ) : null}
            {approvalRecords.length ? (
              <div className="history-list">
                {approvalRecords.map((record) => (
                  <div key={record.id} className="history-card">
                    <div>
                      <strong>{record.target_level}</strong> {record.status}
                    </div>
                    <div>
                      {new Date(record.approved_at).toLocaleString()} · {record.approved_by}
                    </div>
                    {record.notes ? <div>{record.notes}</div> : null}
                  </div>
                ))}
              </div>
            ) : (
              <p>No review history yet.</p>
            )}

            {feedbackTarget?.level === 'test_case' ? (
              <>
                <h2>Approved versions</h2>
                {versionRecords.length ? (
                  <div className="history-list">
                    {versionRecords.map((record) => (
                      <div key={record.id} className="history-card">
                        <div>
                          <strong>v{record.version}</strong> · {record.status}
                        </div>
                        <div>{record.title}</div>
                        <div className="history-meta">
                          {record.approved_by} · {new Date(record.approved_at).toLocaleString()}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p>No approved versions stored yet.</p>
                )}
              </>
            ) : null}

            <h2>Audit trail</h2>
            {auditRecords.length ? (
              <div className="history-list">
                {auditRecords.map((record) => (
                  <div key={record.id} className="history-card">
                    <div>
                      <strong>{record.action}</strong> · {record.entity_type}
                    </div>
                    <div className="history-meta">
                      {record.actor} · {new Date(record.created_at).toLocaleString()}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p>No audit events yet for this target.</p>
            )}

            <h2>Feedback</h2>
            <div className="feedback-target-bar">
              <button
                type="button"
                className={feedbackTarget?.level === 'requirement' ? 'active' : 'secondary-button'}
                onClick={() => handleSelectFeedbackTarget('requirement', requirement.id)}
              >
                Requirement
              </button>
              {requirement.scenarios?.map((scenario) => (
                <button
                  key={scenario.id}
                  type="button"
                  className={
                    feedbackTarget?.level === 'scenario' && feedbackTarget.id === scenario.id
                      ? 'active'
                      : 'secondary-button'
                  }
                  onClick={() => handleSelectFeedbackTarget('scenario', scenario.id)}
                >
                  Scenario
                </button>
              ))}
            </div>
            <form className="feedback-form" onSubmit={handleCreateFeedback}>
              <label>
                Feedback type
                <select value={feedbackType} onChange={(event) => setFeedbackType(event.target.value)}>
                  <option value="revise">revise</option>
                  <option value="generate_new">generate new</option>
                  <option value="deprecate">deprecate</option>
                  <option value="accept">accept</option>
                  <option value="reject">reject</option>
                </select>
              </label>
              <label>
                Comment
                <textarea
                  value={feedbackComment}
                  onChange={(event) => setFeedbackComment(event.target.value)}
                  rows={4}
                  required
                />
              </label>
              <label>
                Created by
                <input
                  type="text"
                  value={feedbackCreatedBy}
                  onChange={(event) => setFeedbackCreatedBy(event.target.value)}
                  required
                />
              </label>
              <div className="detail-actions">
                <button className="primary-button" type="submit" disabled={feedbackSaving}>
                  {feedbackSaving ? 'Submitting…' : 'Submit feedback'}
                </button>
              </div>
            </form>
            {feedbackList.length ? (
              <div className="feedback-list">
                {feedbackList.map((feedback) => (
                  <div key={feedback.id} className="history-card">
                    <div>
                      <strong>{feedback.feedback_type}</strong> · {feedback.target_level}
                    </div>
                    <div>{feedback.comment}</div>
                    <div className="history-meta">
                      {feedback.created_by} · {new Date(feedback.created_at).toLocaleString()}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p>No feedback yet for this target.</p>
            )}
          </article>

          <article className="detail-card">
            <h2>Add a new scenario</h2>
            <form onSubmit={handleCreateScenario}>
              <label>
                Title
                <input
                  type="text"
                  value={scenarioForm.title}
                  onChange={(event) => handleScenarioChange('title', event.target.value)}
                  required
                />
              </label>
              <label>
                Description
                <textarea
                  value={scenarioForm.description}
                  onChange={(event) => handleScenarioChange('description', event.target.value)}
                  required
                />
              </label>
              <div className="detail-actions">
                <button className="primary-button" type="submit" disabled={scenarioSaving}>
                  {scenarioSaving ? 'Saving…' : 'Create Scenario'}
                </button>
              </div>
            </form>
          </article>

          <article className="detail-card">
            <h2>Scenarios</h2>
            {requirement.scenarios?.length ? (
              requirement.scenarios.map((scenario) => (
                <div key={scenario.id} className="scenario-card">
                  <div className="scenario-header">
                    <div>
                      <h3>{scenario.title}</h3>
                      <p>{scenario.description}</p>
                    </div>
                    <div className="scenario-actions">
                      <button
                        className="secondary-button"
                        type="button"
                        onClick={() => handleScenarioApproval(scenario.id, 'approve')}
                        disabled={actionSaving}
                      >
                        Approve
                      </button>
                      <button
                        className="secondary-button"
                        type="button"
                        onClick={() => handleScenarioApproval(scenario.id, 'reject')}
                        disabled={actionSaving}
                      >
                        Reject
                      </button>
                      <button
                        className="secondary-button"
                        type="button"
                        onClick={() => handleSelectFeedbackTarget('scenario', scenario.id)}
                      >
                        Add Feedback
                      </button>
                      <button
                        className="secondary-button"
                        type="button"
                        onClick={() =>
                          setActiveTestCaseScenarioId((current) =>
                            current === scenario.id ? null : scenario.id,
                          )
                        }
                      >
                        {activeTestCaseScenarioId === scenario.id ? 'Cancel' : 'Add Test Case'}
                      </button>
                    </div>
                  </div>
                  <p className="scenario-meta">
                    {scenario.type} · {scenario.severity} · {scenario.status} · v{scenario.version}
                  </p>

                  {activeTestCaseScenarioId === scenario.id && (
                    <form onSubmit={(event) => handleCreateTestCase(event, scenario.id)}>
                      <label>
                        Test case title
                        <input
                          type="text"
                          value={testCaseForm.title}
                          onChange={(event) => handleTestCaseChange('title', event.target.value)}
                          required
                        />
                      </label>
                      <label>
                        Description
                        <textarea
                          value={testCaseForm.description}
                          onChange={(event) => handleTestCaseChange('description', event.target.value)}
                          required
                        />
                      </label>
                      <label>
                        Prerequisite
                        <input
                          type="text"
                          value={testCaseForm.prerequisite}
                          onChange={(event) => handleTestCaseChange('prerequisite', event.target.value)}
                        />
                      </label>
                      <div className="detail-actions">
                        <button className="primary-button" type="submit" disabled={testCaseSaving}>
                          {testCaseSaving ? 'Saving…' : 'Create Test Case'}
                        </button>
                      </div>
                    </form>
                  )}

                  {scenario.test_cases?.length ? (
                    <div className="case-list">
                      {scenario.test_cases.map((testCase) => (
                        <div key={testCase.id} className="case-card">
                          <div className="case-card-header">
                            <h4>{testCase.title}</h4>
                            <div className="case-actions">
                              <button
                                className="secondary-button"
                                type="button"
                                onClick={() => handleTestCaseApproval(testCase.id, 'approve')}
                                disabled={actionSaving}
                              >
                                Approve
                              </button>
                              <button
                                className="secondary-button"
                                type="button"
                                onClick={() => handleTestCaseApproval(testCase.id, 'reject')}
                                disabled={actionSaving}
                              >
                                Reject
                              </button>
                              <button
                                className="secondary-button"
                                type="button"
                                onClick={() => handleSelectFeedbackTarget('test_case', testCase.id)}
                              >
                                Add Feedback
                              </button>
                            </div>
                          </div>
                          <p>{testCase.description}</p>
                          <p className="case-meta">
                            {testCase.type} · {testCase.severity} · {testCase.status} · v{testCase.version} ·{' '}
                            {testCase.locked ? 'locked' : 'editable'} · {testCase.repository_status}
                          </p>
                          {testCase.repository_synced_at ? (
                            <p className="case-meta">
                              Repository sync: {new Date(testCase.repository_synced_at).toLocaleString()}
                            </p>
                          ) : null}
                          {testCase.steps?.map((step) => (
                            <div key={step.step_number} className="case-step">
                              <strong>Step {step.step_number}:</strong> {step.action}
                              <div className="expected-result">Expected: {step.expected_result}</div>
                            </div>
                          ))}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p>No test cases created yet for this scenario.</p>
                  )}
                </div>
              ))
            ) : (
              <p>No scenarios available yet.</p>
            )}
          </article>
        </section>
      ) : (
        <div className="status-message">Requirement not found.</div>
      )}
    </main>
  );
}
