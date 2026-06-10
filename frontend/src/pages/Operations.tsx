import { FormEvent, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  cleanupRequirementText,
  CleanupResult,
  createGovernancePolicy,
  EvaluationRunSummary,
  getGovernancePolicies,
  getMonitoringSummary,
  GovernancePolicySummary,
  importJiraRequirements,
  IntegrationRunSummary,
  MonitoringSummary,
  RepositorySyncRunSummary,
  runEvaluationSuite,
  syncTestRepository,
} from '../api';

export default function OperationsPage() {
  const [jiraPath, setJiraPath] = useState('QA-101, QA-102');
  const [repository, setRepository] = useState('enterprise-test-repository');
  const [branch, setBranch] = useState('main');
  const [cleanupText, setCleanupText] = useState('TBD user should validate checkout ASAP');
  const [policyName, setPolicyName] = useState('Default approval policy');
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [monitoring, setMonitoring] = useState<MonitoringSummary | null>(null);
  const [importRun, setImportRun] = useState<IntegrationRunSummary | null>(null);
  const [syncRun, setSyncRun] = useState<RepositorySyncRunSummary | null>(null);
  const [cleanupResult, setCleanupResult] = useState<CleanupResult | null>(null);
  const [evaluationRun, setEvaluationRun] = useState<EvaluationRunSummary | null>(null);
  const [policies, setPolicies] = useState<GovernancePolicySummary[]>([]);

  const refreshOperations = async () => {
    try {
      setError(null);
      const [monitoringData, policyData] = await Promise.all([
        getMonitoringSummary(),
        getGovernancePolicies(),
      ]);
      setMonitoring(monitoringData);
      setPolicies(policyData);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load operations data');
    }
  };

  useEffect(() => {
    refreshOperations();
  }, []);

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
    runAction('import', async () => {
      setImportRun(await importJiraRequirements(jiraPath));
    });
  };

  const handleSync = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    runAction('sync', async () => {
      setSyncRun(await syncTestRepository(repository, branch));
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
          <h2>Jira import</h2>
          <form onSubmit={handleImport}>
            <label>
              Folder or issue keys
              <textarea value={jiraPath} onChange={(event) => setJiraPath(event.target.value)} required />
            </label>
            <div className="detail-actions">
              <button className="primary-button" type="submit" disabled={busy === 'import'}>
                {busy === 'import' ? 'Importing...' : 'Import Jira'}
              </button>
            </div>
          </form>
          {importRun ? <p className="case-meta">Imported: {String(importRun.result.imported_count ?? 0)}</p> : null}
        </article>

        <article className="detail-card">
          <h2>Repository sync</h2>
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
              <button className="primary-button" type="submit" disabled={busy === 'sync'}>
                {busy === 'sync' ? 'Syncing...' : 'Sync repository'}
              </button>
            </div>
          </form>
          {syncRun ? (
            <p className="case-meta">
              Synced {syncRun.synced_count} cases · vectors {syncRun.vector_synced_count}
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
      </section>
    </main>
  );
}
