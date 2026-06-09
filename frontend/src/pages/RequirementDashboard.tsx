import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getRequirements, RequirementSummary } from '../api';
import RequirementCard from '../components/RequirementCard';

const statusOptions = ['draft', 'generated', 'reviewed', 'approved'] as const;

export default function RequirementDashboard() {
  const [requirements, setRequirements] = useState<RequirementSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState<string | undefined>(undefined);

  useEffect(() => {
    async function fetchRequirements() {
      try {
        setLoading(true);
        setError(null);
        const data = await getRequirements(search, status);
        setRequirements(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    }

    fetchRequirements();
  }, [search, status]);

  return (
    <main className="page-container">
      <header className="page-header">
        <div>
          <p className="eyebrow">Enterprise AI Test Case Generator</p>
          <h1>Requirements</h1>
        </div>
        <Link to="/requirements/new" className="primary-button">
          Add Requirement
        </Link>
      </header>

      <section className="filter-bar">
        <input
          type="search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search requirements..."
        />
        <div className="filter-actions">
          <button
            type="button"
            className={!status ? 'active' : ''}
            onClick={() => setStatus(undefined)}
          >
            All
          </button>
          {statusOptions.map((option) => (
            <button
              key={option}
              type="button"
              className={status === option ? 'active' : ''}
              onClick={() => setStatus(option)}
            >
              {option.charAt(0).toUpperCase() + option.slice(1)}
            </button>
          ))}
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
