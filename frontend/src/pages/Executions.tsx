import { FormEvent, useEffect, useMemo, useState } from 'react';
import {
  getExecutionCandidates,
  getTestExecutions,
  ProjectSummary,
  queueTestExecutions,
  TestCaseSummary,
  TestExecutionRunSummary,
} from '../api';

type ExecutionsProps = {
  selectedProject: ProjectSummary | null;
  canExecute: boolean;
};

export default function Executions({ selectedProject, canExecute }: ExecutionsProps) {
  const [candidates, setCandidates] = useState<TestCaseSummary[]>([]);
  const [runs, setRuns] = useState<TestExecutionRunSummary[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [environment, setEnvironment] = useState('staging');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const candidateNames = useMemo(
    () => new Map(candidates.map((candidate) => [candidate.id, candidate.title])),
    [candidates],
  );

  async function refresh() {
    if (!selectedProject) {
      setCandidates([]);
      setRuns([]);
      setSelectedIds([]);
      return;
    }
    try {
      setLoading(true);
      setError(null);
      const [candidateData, runData] = await Promise.all([
        getExecutionCandidates(selectedProject.id),
        getTestExecutions(selectedProject.id),
      ]);
      setCandidates(candidateData);
      setRuns(runData);
      setSelectedIds((current) => current.filter((id) => candidateData.some((item) => item.id === id)));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load executions');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, [selectedProject?.id]);

  function toggle(testCaseId: string) {
    setSelectedIds((current) =>
      current.includes(testCaseId) ? current.filter((id) => id !== testCaseId) : [...current, testCaseId],
    );
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedProject || selectedIds.length === 0) return;
    try {
      setSaving(true);
      setError(null);
      await queueTestExecutions(selectedProject.id, selectedIds, environment.trim());
      setSelectedIds([]);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to queue executions');
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="page-container">
      <header className="page-header">
        <div>
          <p className="eyebrow">Automated validation</p>
          <h1>Test executions</h1>
          <p>Queue approved test-case versions against the configured runner.</p>
        </div>
        <button className="secondary-button" type="button" onClick={refresh} disabled={loading || !selectedProject}>
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
      </header>

      {error ? <div className="status-message status-error" role="alert">{error}</div> : null}
      {!selectedProject ? <div className="status-message">Select a project to view executions.</div> : null}

      {selectedProject && canExecute ? (
        <section className="detail-card">
          <h2>Queue approved cases</h2>
          <form onSubmit={submit}>
            <label>
              Environment
              <input value={environment} onChange={(event) => setEnvironment(event.target.value)} required />
            </label>
            <div className="execution-candidate-list">
              {candidates.map((candidate) => (
                <label className="history-card execution-candidate" key={candidate.id}>
                  <input
                    type="checkbox"
                    checked={selectedIds.includes(candidate.id)}
                    onChange={() => toggle(candidate.id)}
                  />
                  <span>
                    <strong>{candidate.title}</strong>
                    <small>Version {candidate.version} · {candidate.steps?.length ?? 0} steps</small>
                  </span>
                </label>
              ))}
              {candidates.length === 0 ? <p>No approved test cases are ready to execute.</p> : null}
            </div>
            <button
              className="primary-button"
              type="submit"
              disabled={saving || selectedIds.length === 0 || !environment.trim()}
            >
              {saving ? 'Queueing…' : `Run selected (${selectedIds.length})`}
            </button>
          </form>
        </section>
      ) : null}

      <section className="detail-card">
        <h2>Run history</h2>
        <div className="history-list">
          {runs.map((run) => (
            <article className="history-card" key={run.id}>
              <div className="history-card-header">
                <strong>{candidateNames.get(run.test_case_id) ?? `Test case ${run.test_case_id.slice(0, 8)}`}</strong>
                <span className={`status-pill status-${run.status}`}>{run.status}</span>
              </div>
              <span>{run.environment} · Version {run.test_case_version}</span>
              <small>{new Date(run.created_at).toLocaleString()}</small>
              {Object.keys(run.result).length > 0 ? <pre>{JSON.stringify(run.result, null, 2)}</pre> : null}
            </article>
          ))}
          {selectedProject && runs.length === 0 ? <p>No execution history yet.</p> : null}
        </div>
      </section>
    </main>
  );
}
