import { FormEvent, useState } from 'react';
import { Link } from 'react-router-dom';

import { ProjectSummary, semanticSearch, SemanticSearchResult } from '../api';


type Props = {
  selectedProject: ProjectSummary | null;
};


export default function SemanticSearchPage({ selectedProject }: Props) {
  const [query, setQuery] = useState('');
  const [entityType, setEntityType] = useState<SemanticSearchResult['entity_type'] | ''>('');
  const [results, setResults] = useState<SemanticSearchResult[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedProject) {
      setError('Select a project before searching.');
      return;
    }
    try {
      setBusy(true);
      setError(null);
      setResults(await semanticSearch(selectedProject.id, query.trim(), entityType || undefined));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Semantic search failed');
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="page-container">
      <header className="page-header">
        <div>
          <p className="eyebrow">Project-scoped retrieval</p>
          <h1>Semantic search</h1>
          <p>Search indexed requirements, approved test cases, and feedback by meaning.</p>
        </div>
      </header>

      {error ? <div className="status-message status-error" role="alert">{error}</div> : null}
      <section className="detail-card">
        <form onSubmit={handleSubmit}>
          <label>
            Search {selectedProject?.name ?? 'selected project'}
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              minLength={2}
              maxLength={500}
              required
              placeholder="Expired token, audit trail, boundary coverage..."
            />
          </label>
          <label>
            Artifact type
            <select value={entityType} onChange={(event) => setEntityType(event.target.value as typeof entityType)}>
              <option value="">All indexed artifacts</option>
              <option value="requirement">Requirements</option>
              <option value="test_case">Approved test cases</option>
              <option value="feedback">Feedback</option>
            </select>
          </label>
          <button className="primary-button" type="submit" disabled={busy || !selectedProject || query.trim().length < 2}>
            {busy ? 'Searching...' : 'Search'}
          </button>
        </form>
      </section>

      <section className="history-list" aria-live="polite">
        {results.map((result) => {
          const requirementId = result.entity_type === 'requirement'
            ? result.entity_id
            : typeof result.metadata.requirement_id === 'string' ? result.metadata.requirement_id : null;
          return (
            <article className="history-card" key={result.vector_id}>
              <div className="detail-actions">
                <span className="status-pill">{result.entity_type.replace('_', ' ')}</span>
                <span className="similarity-pill">{Math.round(result.score * 100)}%</span>
              </div>
              <h2>{result.title}</h2>
              <p>{result.text}</p>
              {requirementId ? <Link to={`/requirements/${requirementId}`}>Open requirement</Link> : null}
            </article>
          );
        })}
        {!busy && results.length === 0 ? <p>No semantic results loaded.</p> : null}
      </section>
    </main>
  );
}
