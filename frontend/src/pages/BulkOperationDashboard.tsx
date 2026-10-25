import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { BulkOperationJob, ProjectSummary, getBulkOperations } from '../api';

interface Props { selectedProject: ProjectSummary | null; }

const operationLabels = {
  generate_test_cases: 'Test-case generation',
  impact_analysis: 'Impact analysis',
} as const;

export default function BulkOperationDashboard({ selectedProject }: Props) {
  const [jobs, setJobs] = useState<BulkOperationJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    const load = async () => {
      if (!selectedProject) { setJobs([]); setLoading(false); return; }
      try {
        const data = await getBulkOperations(selectedProject.id);
        if (!cancelled) {
          setJobs(data); setError(null); setLoading(false);
          if (data.some((job) => job.status === 'queued' || job.status === 'processing')) timer = window.setTimeout(load, 2000);
        }
      } catch (err) {
        if (!cancelled) { setError(err instanceof Error ? err.message : 'Unable to load batch runs'); setLoading(false); }
      }
    };
    void load();
    return () => { cancelled = true; if (timer) window.clearTimeout(timer); };
  }, [selectedProject]);

  return (
    <main className="page-container">
      <header className="page-header">
        <div><p className="eyebrow">Operations</p><h1>Batch runs</h1><p className="page-subtitle">Queued bulk generation and impact-analysis activity for this project.</p></div>
        <Link className="secondary-button" to="/requirements">Back to requirements</Link>
      </header>
      {!selectedProject ? <div className="status-message">Create or select a project to view batch runs.</div> : null}
      {loading ? <div className="status-message">Loading batch runs...</div> : null}
      {error ? <div className="status-message status-error">{error}</div> : null}
      {selectedProject && !loading && !error ? (
        <>
          <section className="table-panel" aria-label="Bulk operation runs">
            {jobs.length === 0 ? <div className="status-message">No batch runs yet.</div> : (
              <div className="table-scroll"><table className="data-table"><thead><tr><th>Operation</th><th>Status</th><th>Progress</th><th>Requested by</th><th>Created</th><th>Run ID</th></tr></thead><tbody>
                {jobs.map((job) => { const progress = job.total_count ? Math.round(((job.completed_count + job.failed_count) / job.total_count) * 100) : 0; return (
                  <tr key={job.id}><td>{operationLabels[job.operation_type]}</td><td><span className={`status-badge status-${job.status}`}>{job.status}</span></td><td>{progress}% ({job.completed_count + job.failed_count}/{job.total_count}){job.failed_count ? ` · ${job.failed_count} failed` : ''}</td><td>{job.requested_by}</td><td>{new Date(job.created_at).toLocaleString()}</td><td><code>{job.id.slice(0, 8)}</code></td></tr>
                ); })}
              </tbody></table></div>
            )}
          </section>
          {jobs.some((job) => (job.result.items?.length ?? 0) > 0) ? <section className="table-panel" aria-label="Batch item status">
            <h2>Requirement item status</h2>
            <div className="table-scroll"><table className="data-table"><thead><tr><th>Run</th><th>Operation</th><th>Requirement</th><th>Status</th><th>Message</th></tr></thead><tbody>
              {jobs.flatMap((job) => (job.result.items ?? []).map((item) => <tr key={`${job.id}-${item.requirement_id}`}><td><code>{job.id.slice(0, 8)}</code></td><td>{operationLabels[job.operation_type]}</td><td><code>{item.requirement_id}</code></td><td><span className={`status-badge status-${item.status}`}>{item.status}</span></td><td>{item.message || '—'}</td></tr>))}
            </tbody></table></div>
          </section> : null}
        </>
      ) : null}
    </main>
  );
}
