import { FormEvent, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  acknowledgeAlert,
  AlertSummary,
  cleanupRequirementText,
  CleanupResult,
  ComplianceEvidenceExport,
  ComplianceProfile,
  createSemanticCalibration,
  createGovernancePolicy,
  DependencyHealthSummary,
  EvaluationRunSummary,
  getGovernancePolicies,
  getAlerts,
  getComplianceProfile,
  getDependencyHealth,
  getMonitoringSummary,
  getOutboxEvents,
  getSemanticCalibrations,
  GovernancePolicySummary,
  importJiraRequirements,
  importRequirementFile,
  IntegrationRunSummary,
  MonitoringSummary,
  OutboxEventSummary,
  RepositorySyncRunSummary,
  SemanticCalibrationSample,
  SemanticCalibrationSummary,
  ProjectSummary,
  runEvaluationSuite,
  retryOutboxEvent,
  syncTestRepository,
  updateComplianceProfile,
  exportComplianceEvidence,
} from '../api';

type OperationsPageProps = {
  selectedProject: ProjectSummary | null;
};

export default function OperationsPage({ selectedProject }: OperationsPageProps) {
  const [jiraJql, setJiraJql] = useState('ORDER BY updated DESC');
  const [repository, setRepository] = useState('enterprise-test-repository');
  const [branch, setBranch] = useState('main');
  const [cleanupText, setCleanupText] = useState('TBD user should validate checkout ASAP');
  const [policyName, setPolicyName] = useState('Default approval policy');
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [monitoring, setMonitoring] = useState<MonitoringSummary | null>(null);
  const [importRun, setImportRun] = useState<IntegrationRunSummary | null>(null);
  const [syncRun, setSyncRun] = useState<RepositorySyncRunSummary | null>(null);
  const [uploadRun, setUploadRun] = useState<IntegrationRunSummary | null>(null);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [cleanupResult, setCleanupResult] = useState<CleanupResult | null>(null);
  const [evaluationRun, setEvaluationRun] = useState<EvaluationRunSummary | null>(null);
  const [policies, setPolicies] = useState<GovernancePolicySummary[]>([]);
  const [dependencies, setDependencies] = useState<DependencyHealthSummary | null>(null);
  const [outboxEvents, setOutboxEvents] = useState<OutboxEventSummary[]>([]);
  const [alerts, setAlerts] = useState<AlertSummary[]>([]);
  const [compliance, setCompliance] = useState<ComplianceProfile | null>(null);
  const [complianceExport, setComplianceExport] = useState<ComplianceEvidenceExport | null>(null);
  const [calibrations, setCalibrations] = useState<SemanticCalibrationSummary[]>([]);
  const [frameworks, setFrameworks] = useState('SOC2, ISO27001');
  const [retentionDays, setRetentionDays] = useState(365);
  const [approvalNotesRequired, setApprovalNotesRequired] = useState(false);
  const [calibrationData, setCalibrationData] = useState(JSON.stringify([
    { similarity: 0.96, expected_action: 'duplicate' },
    { similarity: 0.91, expected_action: 'duplicate' },
    { similarity: 0.86, expected_action: 'duplicate' },
    { similarity: 0.74, expected_action: 'update' },
    { similarity: 0.68, expected_action: 'update' },
    { similarity: 0.57, expected_action: 'update' },
    { similarity: 0.41, expected_action: 'unrelated' },
    { similarity: 0.30, expected_action: 'unrelated' },
    { similarity: 0.20, expected_action: 'unrelated' },
    { similarity: 0.10, expected_action: 'unrelated' },
  ], null, 2));

  const refreshOperations = async () => {
    try {
      setError(null);
      const [monitoringData, policyData, dependencyData, outboxData, alertData, complianceData, calibrationRuns] = await Promise.all([
        getMonitoringSummary(),
        getGovernancePolicies(),
        getDependencyHealth(),
        getOutboxEvents(),
        getAlerts(selectedProject?.id),
        selectedProject ? getComplianceProfile(selectedProject.id) : Promise.resolve(null),
        selectedProject ? getSemanticCalibrations(selectedProject.id) : Promise.resolve([]),
      ]);
      setMonitoring(monitoringData);
      setPolicies(policyData);
      setDependencies(dependencyData);
      setOutboxEvents(outboxData);
      setAlerts(alertData);
      setCompliance(complianceData);
      setCalibrations(calibrationRuns);
      if (complianceData) {
        setFrameworks(complianceData.frameworks.join(', '));
        setRetentionDays(complianceData.evidence_retention_days);
        setApprovalNotesRequired(complianceData.approval_notes_required);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load operations data');
    }
  };

  useEffect(() => {
    refreshOperations();
  }, [selectedProject?.id]);

  const runAction = async (name: string, action: () => Promise<void>) => {
    try {
      setBusy(name);
      setError(null);
      await action();
      await refreshOperations();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Operation failed');
    } finally {
      setBusy(null);
    }
  };

  const handleImport = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedProject) {
      setError('Select a project before importing Jira requirements.');
      return;
    }
    runAction('import', async () => {
      setImportRun(await importJiraRequirements(selectedProject.id, jiraJql));
    });
  };

  const handleFileImport = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedProject || !uploadFile) {
      setError('Select a project and requirement file before importing.');
      return;
    }
    runAction('file-import', async () => {
      setUploadRun(await importRequirementFile(selectedProject.id, uploadFile));
      setUploadFile(null);
    });
  };

  const handleRetryOutbox = (eventId: string) => {
    runAction(`retry-${eventId}`, async () => {
      await retryOutboxEvent(eventId);
    });
  };

  const handleAcknowledgeAlert = (alertId: string) => {
    runAction(`ack-${alertId}`, async () => {
      await acknowledgeAlert(alertId);
    });
  };

  const handleSync = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedProject) {
      setError('Select a project before syncing approved test cases.');
      return;
    }
    runAction('sync', async () => {
      setSyncRun(await syncTestRepository(selectedProject.id, repository, branch));
    });
  };

  const handleCleanup = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    runAction('cleanup', async () => {
      setCleanupResult(await cleanupRequirementText(cleanupText));
    });
  };

  const handleEvaluation = () => {
    runAction('evaluation', async () => {
      setEvaluationRun(await runEvaluationSuite());
    });
  };

  const handlePolicy = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    runAction('policy', async () => {
      await createGovernancePolicy({
        name: policyName,
        policy_type: 'approval',
        created_by: 'system',
        rules: {
          required_role: 'approver',
          quality_score_minimum: 85,
          approved_cases_locked: true,
        },
      });
    });
  };

  const handleCompliance = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedProject) return;
    runAction('compliance', async () => {
      setCompliance(await updateComplianceProfile(selectedProject.id, {
        frameworks: frameworks.split(',').map((item) => item.trim()).filter(Boolean),
        evidence_retention_days: retentionDays,
        evidence_export_enabled: true,
        pseudonymize_actors: true,
        approval_notes_required: approvalNotesRequired,
      }));
    });
  };

  const handleEvidenceExport = () => {
    if (!selectedProject) return;
    runAction('evidence', async () => {
      setComplianceExport(await exportComplianceEvidence(selectedProject.id));
    });
  };

  const handleCalibration = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedProject) return;
    runAction('calibration', async () => {
      const parsed = JSON.parse(calibrationData) as SemanticCalibrationSample[];
      await createSemanticCalibration(selectedProject.id, parsed, true);
    });
  };

  return (
    <main className="page-container">
      <header className="page-header">
        <div>
          <p className="eyebrow">Enterprise operations</p>
          <h1>Integrations and governance</h1>
        </div>
        <Link className="secondary-button" to="/requirements">
          Requirements
        </Link>
      </header>

      {error ? <div className="status-message status-error">{error}</div> : null}

      <section className="ops-grid">
        <article className="detail-card">
          <h2>Monitoring</h2>
          {monitoring ? (
            <div className="impact-summary-grid">
              {Object.entries(monitoring.metrics).map(([key, value]) => (
                <div className="history-card" key={key}>
                  <strong>{value}</strong>
                  <span>{key.replace(/_/g, ' ')}</span>
                </div>
              ))}
            </div>
          ) : (
            <p>No monitoring snapshot loaded.</p>
          )}
          <button className="secondary-button" type="button" onClick={refreshOperations}>
            Refresh
          </button>
        </article>

        <article className="detail-card">
          <h2>Dependency health</h2>
          <p className="case-meta" role="status">
            Overall: {dependencies?.status ?? 'checking'}
          </p>
          <div className="history-list">
            {dependencies?.dependencies.map((dependency) => (
              <div className="history-card" key={dependency.name}>
                <strong>{dependency.name.replace(/_/g, ' ')}</strong>
                <span className={`status-pill status-${dependency.status}`}>{dependency.status.replace(/_/g, ' ')}</span>
              </div>
            ))}
          </div>
        </article>

        <article className="detail-card">
          <h2>File import</h2>
          <p className="case-meta">UTF-8 TXT, Markdown, CSV, or JSON · Destination: {selectedProject?.name ?? 'Select a project'}</p>
          <form onSubmit={handleFileImport}>
            <label>
              Requirement file
              <input
                type="file"
                accept=".txt,.md,.csv,.json,text/plain,text/markdown,text/csv,application/json"
                onChange={(event) => setUploadFile(event.target.files?.[0] ?? null)}
                required
              />
            </label>
            <div className="detail-actions">
              <button
                className="primary-button"
                type="submit"
                disabled={busy === 'file-import' || !selectedProject || !uploadFile}
              >
                {busy === 'file-import' ? 'Importing...' : 'Import file'}
              </button>
            </div>
          </form>
          {uploadRun ? (
            <p className="case-meta" role="status">
              Created {String(uploadRun.result.created_count ?? 0)} · Existing {String(uploadRun.result.existing_count ?? 0)}
            </p>
          ) : null}
        </article>

        <article className="detail-card">
          <h2>Jira import</h2>
          <p className="case-meta">Destination: {selectedProject?.name ?? 'Select a project'}</p>
          <form onSubmit={handleImport}>
            <label>
              JQL query
              <textarea value={jiraJql} onChange={(event) => setJiraJql(event.target.value)} required />
            </label>
            <div className="detail-actions">
              <button className="primary-button" type="submit" disabled={busy === 'import' || !selectedProject}>
                {busy === 'import' ? 'Importing...' : 'Import Jira'}
              </button>
            </div>
          </form>
          {importRun ? <p className="case-meta">Imported: {String(importRun.result.imported_count ?? 0)}</p> : null}
        </article>

        <article className="detail-card">
          <h2>Repository sync</h2>
          <p className="case-meta">Project: {selectedProject?.name ?? 'Select a project'}</p>
          <form onSubmit={handleSync}>
            <label>
              Repository
              <input value={repository} onChange={(event) => setRepository(event.target.value)} required />
            </label>
            <label>
              Branch
              <input value={branch} onChange={(event) => setBranch(event.target.value)} required />
            </label>
            <div className="detail-actions">
              <button className="primary-button" type="submit" disabled={busy === 'sync' || !selectedProject}>
                {busy === 'sync' ? 'Syncing...' : 'Sync repository'}
              </button>
            </div>
          </form>
          {syncRun ? (
            <p className="case-meta">
              {syncRun.status === 'queued' ? 'Queued' : 'Synced'} {String(syncRun.details.queued_count ?? syncRun.synced_count)} cases
            </p>
          ) : null}
        </article>

        <article className="detail-card">
          <h2>NLP cleanup</h2>
          <form onSubmit={handleCleanup}>
            <label>
              Requirement text
              <textarea value={cleanupText} onChange={(event) => setCleanupText(event.target.value)} required />
            </label>
            <div className="detail-actions">
              <button className="primary-button" type="submit" disabled={busy === 'cleanup'}>
                {busy === 'cleanup' ? 'Cleaning...' : 'Clean text'}
              </button>
            </div>
          </form>
          {cleanupResult ? (
            <div className="history-card">
              <strong>Cleaned</strong>
              <p>{cleanupResult.cleaned_text}</p>
              <p className="case-meta">Issues: {cleanupResult.issues.length}</p>
            </div>
          ) : null}
        </article>

        <article className="detail-card">
          <h2>Evaluation</h2>
          <div className="detail-actions">
            <button className="primary-button" type="button" onClick={handleEvaluation} disabled={busy === 'evaluation'}>
              {busy === 'evaluation' ? 'Running...' : 'Run quality suite'}
            </button>
          </div>
          {evaluationRun ? (
            <div className="history-card">
              <strong>{evaluationRun.score}/100</strong>
              <p>{evaluationRun.status}</p>
            </div>
          ) : null}
        </article>

        <article className="detail-card">
          <h2>Governance policies</h2>
          <form onSubmit={handlePolicy}>
            <label>
              Policy name
              <input value={policyName} onChange={(event) => setPolicyName(event.target.value)} required />
            </label>
            <div className="detail-actions">
              <button className="primary-button" type="submit" disabled={busy === 'policy'}>
                {busy === 'policy' ? 'Saving...' : 'Create policy'}
              </button>
            </div>
          </form>
          <div className="history-list">
            {policies.map((policy) => (
              <div className="history-card" key={policy.id}>
                <strong>{policy.name}</strong>
                <p className="case-meta">
                  {policy.policy_type} · {policy.status}
                </p>
              </div>
            ))}
          </div>
        </article>

        <article className="detail-card">
          <h2>Project compliance</h2>
          <p className="case-meta">Controls and export evidence for {selectedProject?.name ?? 'a selected project'}.</p>
          <form onSubmit={handleCompliance}>
            <label>
              Frameworks
              <input value={frameworks} onChange={(event) => setFrameworks(event.target.value)} />
            </label>
            <label>
              Evidence retention days
              <input type="number" min="30" max="3650" value={retentionDays} onChange={(event) => setRetentionDays(Number(event.target.value))} />
            </label>
            <label>
              <input type="checkbox" checked={approvalNotesRequired} onChange={(event) => setApprovalNotesRequired(event.target.checked)} />
              Require approval notes
            </label>
            <div className="detail-actions">
              <button className="primary-button" type="submit" disabled={!selectedProject || busy === 'compliance'}>
                {busy === 'compliance' ? 'Saving...' : 'Save compliance profile'}
              </button>
              <button className="secondary-button" type="button" onClick={handleEvidenceExport} disabled={!selectedProject || busy === 'evidence'}>
                {busy === 'evidence' ? 'Exporting...' : 'Generate evidence export'}
              </button>
            </div>
          </form>
          {compliance ? <p className="case-meta">Active retention: {compliance.evidence_retention_days} days</p> : null}
          {complianceExport ? (
            <p className="case-meta" role="status">
              Evidence SHA-256: {complianceExport.sha256}
              {complianceExport.is_complete
                ? ' (complete)'
                : ` (truncated: ${complianceExport.truncated_sections.join(', ')})`}
            </p>
          ) : null}
        </article>

        <article className="detail-card">
          <h2>Semantic calibration</h2>
          <p className="case-meta">Apply thresholds from labeled similarity outcomes. Include all three actions and at least 10 samples.</p>
          <form onSubmit={handleCalibration}>
            <label>
              Labeled samples (JSON)
              <textarea value={calibrationData} onChange={(event) => setCalibrationData(event.target.value)} rows={12} required />
            </label>
            <button className="primary-button" type="submit" disabled={!selectedProject || busy === 'calibration'}>
              {busy === 'calibration' ? 'Calibrating...' : 'Calibrate and apply'}
            </button>
          </form>
          {calibrations[0] ? (
            <p className="case-meta">Latest: {calibrations[0].status} · macro F1 {calibrations[0].metrics.macro_f1}</p>
          ) : <p className="case-meta">No calibration evidence yet.</p>}
        </article>

        <article className="detail-card ops-span-full">
          <h2>Operational alerts</h2>
          <p className="case-meta">Execution failures and exhausted deliveries that need human attention.</p>
          <div className="history-list">
            {alerts.length ? alerts.map((alert) => (
              <div className="history-card" key={alert.id}>
                <div className="history-card-header">
                  <strong>{alert.title}</strong>
                  <span className={`status-pill status-${alert.severity}`}>{alert.severity}</span>
                </div>
                <p className="case-meta">
                  {alert.category.replace(/_/g, ' ')} · delivery {alert.delivery_status.replace(/_/g, ' ')}
                </p>
                <pre>{JSON.stringify(alert.details, null, 2)}</pre>
                {alert.status === 'open' ? (
                  <button
                    className="secondary-button"
                    type="button"
                    onClick={() => handleAcknowledgeAlert(alert.id)}
                    disabled={busy === `ack-${alert.id}`}
                  >
                    {busy === `ack-${alert.id}` ? 'Acknowledging...' : 'Acknowledge'}
                  </button>
                ) : <span className="status-pill status-completed">Acknowledged</span>}
              </div>
            )) : <p>No operational alerts found.</p>}
          </div>
        </article>

        <article className="detail-card ops-span-full">
          <h2>Outbox delivery</h2>
          <p className="case-meta">Recent indexing and repository delivery events. Failed events can be safely requeued.</p>
          <div className="history-list">
            {outboxEvents.length ? outboxEvents.map((item) => (
              <div className="history-card" key={item.id}>
                <strong>{item.event_type}</strong>
                <p className="case-meta">{item.status} · attempts {item.attempts} · {item.aggregate_type} {item.aggregate_id}</p>
                {item.last_error ? <p className="status-message status-error">{item.last_error}</p> : null}
                {item.status === 'failed' ? (
                  <button
                    className="secondary-button"
                    type="button"
                    onClick={() => handleRetryOutbox(item.id)}
                    disabled={busy === `retry-${item.id}`}
                  >
                    {busy === `retry-${item.id}` ? 'Requeuing...' : 'Retry event'}
                  </button>
                ) : null}
              </div>
            )) : <p>No outbox events found.</p>}
          </div>
        </article>
      </section>
    </main>
  );
}
