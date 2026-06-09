import { useEffect, useState } from 'react';
import { getRequirements, RequirementSummary } from '../api';
import RequirementCard from '../components/RequirementCard';

export default function RequirementDashboard() {
  const [requirements, setRequirements] = useState<RequirementSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchRequirements() {
      try {
        setLoading(true);
        setError(null);
        const data = await getRequirements();
        setRequirements(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    }

    fetchRequirements();
  }, []);

  return (
    <main className="page-container">
      <header className="page-header">
        <div>
          <p className="eyebrow">Enterprise AI Test Case Generator</p>
          <h1>Requirements</h1>
        </div>
        <button className="primary-button">Add Requirement</button>
      </header>

      <section className="filter-bar">
        <input type="search" placeholder="Search requirements..." />
        <div className="filter-actions">
          <button>Draft</button>
          <button>Generated</button>
          <button>Reviewed</button>
          <button>Approved</button>
        </div>
      </section>

      {loading ? (
        <div className="status-message">Loading requirements...</div>
      ) : error ? (
        <div className="status-message status-error">{error}</div>
      ) : (
        <section className="card-grid">
          {requirements.length > 0 ? (
            requirements.map((requirement) => (
              <RequirementCard key={requirement.id} requirement={requirement} />
            ))
          ) : (
            <div className="status-message">No requirements found.</div>
          )}
        </section>
      )}
    </main>
  );
}
