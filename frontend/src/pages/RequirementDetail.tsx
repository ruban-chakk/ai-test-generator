import { FormEvent, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  approveRequirement,
  approveScenario,
  approveTestCase,
  createFeedback,
  createScenarioForRequirement,
  createTestCaseForScenario,
  deprecateImpactedTestCase,
  evaluateQuality,
  flagImpactedTestCaseForUpdate,
  getAudit,
  getApprovals,
  getFeedback,
  getQualityEvaluations,
  getRevisions,
  getRequirementImpact,
  getTestCaseVersions,
  generateRequirementDraft,
  getRequirement,
  rejectRequirement,
  rejectScenario,
  rejectTestCase,
  ApprovalRecordSummary,
  AuditLogSummary,
  FeedbackSummary,
  ImpactAnalysisSummary,
  ImpactCandidate,
  QualityEvaluationSummary,
  RequirementDetail,
  RevisionRecordSummary,
  TestCaseVersionSummary,
  ValidationResult,
  processFeedbackRevision,
  validateTarget,
} from '../api';

function CustomFields({ fields }: { fields?: Record<string, unknown> }) {
  if (!fields || !Object.keys(fields).length) return null;
  return (
    <dl className="detail-list" aria-label="Custom fields">
      {Object.entries(fields).map(([name, value]) => (
        <div className="detail-row" key={name}>
          <dt>{name.replace(/_/g, ' ')}</dt>
          <dd>{typeof value === 'string' ? value : JSON.stringify(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

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
  const [historyError, setHistoryError] = useState<string | null>(null);

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
  const [feedbackModalOpen, setFeedbackModalOpen] = useState(false);
  const [feedbackList, setFeedbackList] = useState<FeedbackSummary[]>([]);
  const [approvalRecords, setApprovalRecords] = useState<ApprovalRecordSummary[]>([]);
  const [auditRecords, setAuditRecords] = useState<AuditLogSummary[]>([]);
  const [versionRecords, setVersionRecords] = useState<TestCaseVersionSummary[]>([]);
  const [revisionRecords, setRevisionRecords] = useState<RevisionRecordSummary[]>([]);
  const [qualityRecords, setQualityRecords] = useState<QualityEvaluationSummary[]>([]);
  const [impactAnalysis, setImpactAnalysis] = useState<ImpactAnalysisSummary | null>(null);
  const [validationResult, setValidationResult] = useState<ValidationResult | null>(null);
  const [validationSaving, setValidationSaving] = useState(false);
  const [revisionSaving, setRevisionSaving] = useState<string | null>(null);
  const [qualitySaving, setQualitySaving] = useState(false);
  const [impactSaving, setImpactSaving] = useState(false);
  const [impactActionSaving, setImpactActionSaving] = useState<string | null>(null);

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
      setHistoryError(null);
      const [feedbackData, approvalsData, auditData, versionData, revisionsData, qualityData] = await Promise.all([
        getFeedback(targetLevel, targetId),
        getApprovals(targetLevel, targetId),
        getAudit(targetLevel, targetId),
        targetLevel === 'test_case' ? getTestCaseVersions(targetId) : Promise.resolve([]),
        getRevisions(targetLevel, targetId),
        getQualityEvaluations(targetLevel, targetId),
      ]);
      setFeedbackList(feedbackData);
      setApprovalRecords(approvalsData);
      setAuditRecords(auditData);
      setVersionRecords(versionData);
      setRevisionRecords(revisionsData);
      setQualityRecords(qualityData);
    } catch (err) {
      setHistoryError(err instanceof Error ? err.message : 'Unable to load review history');
    }
  };

  const handleSelectFeedbackTarget = (
    level: 'requirement' | 'scenario' | 'test_case',
    targetId: string,
    openModal = false,
  ) => {
    setFeedbackTarget({ level, id: targetId });
    setValidationResult(null);
    if (openModal) setFeedbackModalOpen(true);
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

  const handleEvaluateQuality = async () => {
    if (!feedbackTarget) {
      setError('Select a review target first');
      return;
    }

    try {
      setQualitySaving(true);
      setError(null);
      await evaluateQuality(feedbackTarget.level, feedbackTarget.id);
      await refreshHistory(feedbackTarget.id, feedbackTarget.level);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to evaluate quality');
    } finally {
      setQualitySaving(false);
    }
  };

  const handleRunImpactAnalysis = async () => {
    if (!id) {
      setError('Requirement ID is missing');
      return;
    }

    try {
      setImpactSaving(true);
      setError(null);
      const result = await getRequirementImpact(id);
      setImpactAnalysis(result);
      await refreshHistory(id, 'requirement');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to run impact analysis');
    } finally {
      setImpactSaving(false);
    }
  };

  const handleImpactAction = async (candidate: ImpactCandidate, action: 'deprecate' | 'review_update') => {
    try {
      setImpactActionSaving(candidate.test_case_id);
      setError(null);
      if (action === 'deprecate') {
        await deprecateImpactedTestCase(candidate.test_case_id, {
          approved_by: feedbackCreatedBy,
          notes: `Applied from impact analysis ${impactAnalysis?.id ?? ''}`,
        });
      } else {
        await flagImpactedTestCaseForUpdate(candidate.test_case_id, {
          approved_by: feedbackCreatedBy,
          notes: `Applied from impact analysis ${impactAnalysis?.id ?? ''}`,
        });
      }
      await refreshRequirement();
      if (id) {
        const result = await getRequirementImpact(id);
        setImpactAnalysis(result);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to apply impact action');
    } finally {
      setImpactActionSaving(null);
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
      setFeedbackModalOpen(false);
      await refreshHistory(feedbackTarget.id, feedbackTarget.level);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to submit feedback');
    } finally {
      setFeedbackSaving(false);
    }
  };

  const handleProcessFeedback = async (feedback: FeedbackSummary, action?: string) => {
    if (!feedbackTarget) return;

    try {
      setRevisionSaving(feedback.id);
      setError(null);
      await processFeedbackRevision({
        feedback_id: feedback.id,
        action: action ?? feedback.feedback_type,
        created_by: feedbackCreatedBy,
        notes: `Processed from ${feedback.feedback_type} feedback`,
      });
      await refreshRequirement();
      await refreshHistory(feedbackTarget.id, feedbackTarget.level);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to process feedback');
    } finally {
      setRevisionSaving(null);
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

  const renderImpactCandidates = (
    title: string,
    candidates: ImpactCandidate[],
    action?: 'deprecate' | 'review_update',
  ) => (
    <div className="impact-group">
      <h3>{title}</h3>
      {candidates.length ? (
        <div className="history-list">
          {candidates.map((candidate) => (
            <div key={`${title}-${candidate.test_case_id}`} className="impact-card">
              <div className="impact-card-header">
                <div>
                  <strong>{candidate.title}</strong>
                  <div className="history-meta">
                    {candidate.type ?? 'case'} · {candidate.severity ?? 'severity'} · {candidate.repository_status}
                  </div>
                </div>
                <span className="similarity-pill">{Math.round(candidate.similarity * 100)}%</span>
              </div>
              <p>{candidate.reason}</p>
              <p className="case-meta">Recommended action: {candidate.recommended_action}</p>
              {action ? (
                <div className="detail-actions">
                  <button
                    className="secondary-button"
                    type="button"
                    onClick={() => handleImpactAction(candidate, action)}
                    disabled={impactActionSaving === candidate.test_case_id}
                  >
                    {impactActionSaving === candidate.test_case_id
                      ? 'Applying...'
                      : action === 'deprecate'
                        ? 'Mark deprecated'
                        : 'Review update'}
                  </button>
                </div>
              ) : null}
            </div>
          ))}
        </div>
      ) : (
        <p>No candidates found.</p>
      )}
    </div>
  );

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
            <CustomFields fields={requirement.metadata_json?.custom_fields as Record<string, unknown> | undefined} />
          </article>

          <article className="detail-card impact-panel">
            <div className="impact-heading">
              <div>
                <h2>Impact analysis</h2>
                <p className="case-meta">Compares this requirement against approved repository test cases.</p>
              </div>
              <button
                className="primary-button"
                type="button"
                onClick={handleRunImpactAnalysis}
                disabled={impactSaving}
              >
                {impactSaving ? 'Analyzing...' : 'Run impact'}
              </button>
            </div>
            {impactAnalysis ? (
              <>
                <div className="impact-summary-grid">
                  <div className="history-card">
                    <strong>{impactAnalysis.duplicates.length}</strong>
                    <span>Duplicates</span>
                  </div>
                  <div className="history-card">
                    <strong>{impactAnalysis.deprecations.length}</strong>
                    <span>Deprecations</span>
                  </div>
                  <div className="history-card">
                    <strong>{impactAnalysis.updates.length}</strong>
                    <span>Updates</span>
                  </div>
                  <div className="history-card">
                    <strong>{impactAnalysis.risk_score}/100</strong>
                    <span>Risk</span>
                  </div>
                  <div className="history-card">
                    <strong>{impactAnalysis.coverage_score}/100</strong>
                    <span>Coverage</span>
                  </div>
                </div>
                <p className="case-meta">
                  Duplicate threshold: {Math.round(impactAnalysis.similarity_threshold * 100)}% · Scanned:{' '}
                  {String(impactAnalysis.summary.approved_cases_scanned ?? 0)}
                </p>
                {renderImpactCandidates('Duplicate candidates', impactAnalysis.duplicates)}
                {renderImpactCandidates('Deprecation candidates', impactAnalysis.deprecations, 'deprecate')}
                {renderImpactCandidates('Update candidates', impactAnalysis.updates, 'review_update')}
              </>
            ) : (
              <p>No impact analysis has been run for this requirement yet.</p>
            )}
          </article>

          <article className="detail-card">
            <h2>Review history</h2>
            {historyError ? (
              <div className="status-message status-warning">
                Review history is unavailable: {historyError}
              </div>
            ) : null}
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
              <button
                className="secondary-button"
                type="button"
                onClick={handleEvaluateQuality}
                disabled={qualitySaving}
              >
                {qualitySaving ? 'Scoring...' : 'Evaluate quality'}
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

            <h2>Quality metrics</h2>
            {qualityRecords.length ? (
              <div className="history-list">
                {qualityRecords.map((record) => (
                  <div key={record.id} className="history-card">
                    <div>
                      <strong>{record.score}/100</strong> · {record.status}
                    </div>
                    <div className="history-meta">
                      {record.evaluated_by} · {new Date(record.created_at).toLocaleString()}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p>No quality evaluations yet for this target.</p>
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

            <h2>Revision trace</h2>
            {revisionRecords.length ? (
              <div className="history-list">
                {revisionRecords.map((record) => (
                  <div key={record.id} className="history-card">
                    <div>
                      <strong>{record.action}</strong> · {record.status}
                    </div>
                    <div className="history-meta">
                      {record.created_by} · {new Date(record.created_at).toLocaleString()}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p>No revision activity yet for this target.</p>
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
            <div className="detail-actions">
              <button className="primary-button" type="button" onClick={() => setFeedbackModalOpen(true)}>
                Add feedback
              </button>
            </div>
            {feedbackList.length ? (
              <div className="feedback-list">
                {feedbackList.map((feedback) => (
                  <div key={feedback.id} className="history-card">
                    <div>
                      <strong>{feedback.feedback_type}</strong> · {feedback.target_level} · {feedback.status}
                    </div>
                    <div>{feedback.comment}</div>
                    <div className="history-meta">
                      {feedback.created_by} · {new Date(feedback.created_at).toLocaleString()}
                    </div>
                    {feedback.resolution_notes ? <div>{feedback.resolution_notes}</div> : null}
                    {feedback.status !== 'resolved' ? (
                      <div className="detail-actions">
                        <button
                          className="secondary-button"
                          type="button"
                          onClick={() => handleProcessFeedback(feedback)}
                          disabled={revisionSaving === feedback.id}
                        >
                          {revisionSaving === feedback.id ? 'Processing...' : 'Process feedback'}
                        </button>
                      </div>
                    ) : null}
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

          <article className="detail-card" id="test-cases">
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
                        onClick={() => handleSelectFeedbackTarget('scenario', scenario.id, true)}
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
                    <div className="table-scroll case-table-wrap">
                      <table className="data-table">
                        <thead>
                          <tr>
                            <th scope="col">Test Case</th>
                            <th scope="col">Type</th>
                            <th scope="col">Severity</th>
                            <th scope="col">Status</th>
                            <th scope="col">Repository</th>
                            <th scope="col">Steps</th>
                            <th scope="col" className="actions-column">
                              Action
                            </th>
                          </tr>
                        </thead>
                        <tbody>
                          {scenario.test_cases.map((testCase) => (
                            <tr key={testCase.id}>
                              <td>
                                <strong>{testCase.title}</strong>
                                <span className="table-description">{testCase.description}</span>
                                {testCase.prerequisite ? (
                                  <span className="table-description">Prerequisite: {testCase.prerequisite}</span>
                                ) : null}
                                <CustomFields fields={testCase.custom_fields_json} />
                              </td>
                              <td>{testCase.type ?? '—'}</td>
                              <td>{testCase.severity ?? '—'}</td>
                              <td>
                                <span className="status-pill">{testCase.status}</span>
                                <span className="table-description">
                                  v{testCase.version} · {testCase.locked ? 'locked' : 'editable'}
                                </span>
                              </td>
                              <td>
                                {testCase.repository_status}
                                {testCase.repository_synced_at ? (
                                  <span className="table-description">
                                    Synced {new Date(testCase.repository_synced_at).toLocaleString()}
                                  </span>
                                ) : null}
                              </td>
                              <td>
                                {testCase.steps?.length ? (
                                  <ol className="step-list">
                                    {testCase.steps.map((step) => (
                                      <li key={step.step_number}>
                                        <strong>{step.action}</strong>
                                        <span>{step.expected_result}</span>
                                      </li>
                                    ))}
                                  </ol>
                                ) : (
                                  '—'
                                )}
                              </td>
                              <td>
                                <div className="table-actions">
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
                                    onClick={() => handleSelectFeedbackTarget('test_case', testCase.id, true)}
                                  >
                                    Add Feedback
                                  </button>
                                </div>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
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

      {feedbackModalOpen ? (
        <div className="modal-backdrop" role="presentation">
          <div className="modal-panel" role="dialog" aria-modal="true" aria-label="Add feedback">
            <div className="modal-header">
              <h2>Add feedback</h2>
              <button className="secondary-button" type="button" onClick={() => setFeedbackModalOpen(false)}>
                Close
              </button>
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
                  {feedbackSaving ? 'Submitting...' : 'Submit feedback'}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
    </main>
  );
}
