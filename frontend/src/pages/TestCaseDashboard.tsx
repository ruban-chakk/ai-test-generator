import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { getTestCases, ProjectSummary, TestCaseInventoryItem } from '../api';

const statuses = ['draft', 'generated', 'reviewed', 'approved', 'rejected'] as const;

export default function TestCaseDashboard({ selectedProject }: { selectedProject: ProjectSummary | null }) {
  const [testCases, setTestCases] = useState<TestCaseInventoryItem[]>([]);
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('');
  const [source, setSource] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedProject) {
      setTestCases([]);
      return;
    }
    setLoading(true);
    setError(null);
    const timer = window.setTimeout(() => {
      getTestCases(selectedProject.id, { search: search.trim() || undefined, status: status || undefined, source: source || undefined })
        .then(setTestCases)
        .catch((err) => setError(err instanceof Error ? err.message : 'Unable to load test cases'))
        .finally(() => setLoading(false));
    }, 180);
    return () => window.clearTimeout(timer);
  }, [selectedProject, search, status, source]);

  const summary = useMemo(() => ({
    total: testCases.length,
    draft: testCases.filter((item) => item.status === 'draft').length,
    approved: testCases.filter((item) => item.status === 'approved').length,
    generated: testCases.filter((item) => item.source === 'generated').length,
  }), [testCases]);

  return (
    <main className="page-container">
      <header className="page-header">
        <div><p className="eyebrow">Test repository</p><h1>Test cases</h1><span className="header-subtitle">Existing, generated, and draft tests for {selectedProject?.name ?? 'the selected project'}.</span></div>
      </header>

      <section className="metric-strip" aria-label="Test case summary">
        <div><span>Total</span><strong>{summary.total}</strong></div>
        <div><span>Draft</span><strong>{summary.draft}</strong></div>
        <div><span>Generated</span><strong>{summary.generated}</strong></div>
        <div><span>Approved</span><strong>{summary.approved}</strong></div>
      </section>

      <section className="filter-bar rich-toolbar" aria-label="Test case filters">
        <label className="search-control"><span className="search-prefix">Search</span><input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Title, ID, requirement" /></label>
        <div className="toolbar-controls">
          <label className="compact-field">Status<select value={status} onChange={(event) => setStatus(event.target.value)}><option value="">All statuses</option>{statuses.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
          <label className="compact-field">Source<select value={source} onChange={(event) => setSource(event.target.value)}><option value="">All sources</option><option value="generated">Generated</option><option value="historical">Historical</option><option value="manual">Manual</option></select></label>
        </div>
      </section>

      {error ? <div className="status-message status-error" role="alert">{error}</div> : null}
      {loading ? <div className="status-message">Loading test cases…</div> : !selectedProject ? <div className="status-message">Select a project to view test cases.</div> : (
        <section className="table-panel" aria-label="All test cases">
          {testCases.length ? <div className="table-scroll"><table className="data-table"><thead><tr><th>Test case</th><th>Requirement / scenario</th><th>Source</th><th>Status</th><th>Repository</th><th>Updated</th></tr></thead><tbody>
            {testCases.map((testCase) => <tr key={testCase.id}>
              <td><Link className="table-primary-link" to={`/requirements/${testCase.requirement_id}/test-cases?case=${testCase.id}`}>{testCase.title}</Link><span className="table-description">{testCase.external_id ?? testCase.id}</span></td>
              <td><Link to={`/requirements/${testCase.requirement_id}`}>{testCase.requirement_title}</Link><span className="table-description">{testCase.scenario_title}</span></td>
              <td><span className="chip">{testCase.source ?? 'generated'}</span></td>
              <td><span className={`status-pill status-${testCase.status}`}>{testCase.status}</span></td>
              <td>{testCase.repository_status}</td>
              <td>{new Date(testCase.updated_at).toLocaleDateString()}</td>
            </tr>)}
          </tbody></table></div> : <div className="empty-state"><h2>No matching test cases</h2><p>Change the filters or generate tests from a requirement.</p><Link className="primary-button" to="/requirements">View requirements</Link></div>}
        </section>
      )}
    </main>
  );
}
