import { FormEvent, useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import {
  ProjectSummary,
  getSavedSearches,
  recordSearchJudgment,
  SavedSearch,
  saveArtifactSearch,
  searchArtifacts,
  SearchMode,
  SemanticSearchResult,
} from '../api';


type Props = {
  selectedProject: ProjectSummary | null;
};

const searchModes: Array<{ value: SearchMode; label: string; description: string }> = [
  {
    value: 'hybrid',
    label: 'Hybrid',
    description: 'Combines meaning with exact terminology and identifiers.',
  },
  {
    value: 'semantic',
    label: 'Semantic',
    description: 'Finds conceptually similar artifacts using embeddings.',
  },
  {
    value: 'keyword',
    label: 'Keyword',
    description: 'Matches exact words, phrases, and requirement identifiers.',
  },
];

function validMode(value: string | null): SearchMode {
  return value === 'semantic' || value === 'keyword' || value === 'hybrid' ? value : 'hybrid';
}

function validEntityType(value: string | null): SemanticSearchResult['entity_type'] | '' {
  return value === 'requirement' || value === 'test_case' || value === 'feedback' ? value : '';
}

function percentage(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export default function SemanticSearchPage({ selectedProject }: Props) {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeQuery = searchParams.get('q')?.trim() ?? '';
  const activeMode = validMode(searchParams.get('mode'));
  const activeEntityType = validEntityType(searchParams.get('type'));
  const activeCustomField = searchParams.get('field')?.trim() ?? '';
  const activeCustomValue = searchParams.get('value') ?? '';
  const [query, setQuery] = useState(activeQuery);
  const [mode, setMode] = useState<SearchMode>(activeMode);
  const [entityType, setEntityType] = useState<SemanticSearchResult['entity_type'] | ''>(activeEntityType);
  const [customField, setCustomField] = useState(activeCustomField);
  const [customValue, setCustomValue] = useState(activeCustomValue);
  const [results, setResults] = useState<SemanticSearchResult[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [savedSearches, setSavedSearches] = useState<SavedSearch[]>([]);
  const [savedName, setSavedName] = useState('');

  useEffect(() => {
    setQuery(activeQuery);
    setMode(activeMode);
    setEntityType(activeEntityType);
    setCustomField(activeCustomField);
    setCustomValue(activeCustomValue);
  }, [activeCustomField, activeCustomValue, activeEntityType, activeMode, activeQuery]);

  useEffect(() => {
    if (!selectedProject) {
      setSavedSearches([]);
      return;
    }
    getSavedSearches(selectedProject.id).then(setSavedSearches).catch(() => setSavedSearches([]));
  }, [selectedProject]);

  useEffect(() => {
    let active = true;
    if (!selectedProject || activeQuery.length < 2) {
      setResults([]);
      setBusy(false);
      return () => { active = false; };
    }
    setBusy(true);
    setError(null);
    const searchRequest = activeCustomField
      ? searchArtifacts(
        selectedProject.id,
        activeQuery,
        activeMode,
        activeEntityType || undefined,
        0,
        activeCustomField,
        activeCustomValue,
      )
      : searchArtifacts(selectedProject.id, activeQuery, activeMode, activeEntityType || undefined);
    searchRequest
      .then((data) => {
        if (active) {
          setResults(data);
          setHasMore(data.length === 20);
        }
      })
      .catch((err: unknown) => {
        if (active) {
          setResults([]);
          setError(err instanceof Error ? err.message : 'Search failed');
        }
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => { active = false; };
  }, [activeCustomField, activeCustomValue, activeEntityType, activeMode, activeQuery, refreshToken, selectedProject]);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedProject) {
      setError('Select a project before searching.');
      return;
    }
    const normalizedQuery = query.trim();
    if (normalizedQuery.length < 2) return;
    const next = new URLSearchParams({ q: normalizedQuery, mode });
    if (entityType) next.set('type', entityType);
    if (customField.trim()) {
      next.set('field', customField.trim());
      next.set('value', customValue);
    }
    const unchanged = next.toString() === searchParams.toString();
    setSearchParams(next, { replace: true });
    if (unchanged) setRefreshToken((value) => value + 1);
  }

  async function handleLoadMore() {
    if (!selectedProject || busy) return;
    setBusy(true);
    setError(null);
    try {
      const next = await searchArtifacts(
        selectedProject.id,
        activeQuery,
        activeMode,
        activeEntityType || undefined,
        results.length,
        activeCustomField || undefined,
        activeCustomField ? activeCustomValue : undefined,
      );
      setResults((current) => [...current, ...next]);
      setHasMore(next.length === 20);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load more results');
    } finally {
      setBusy(false);
    }
  }

  async function handleSaveSearch() {
    if (!selectedProject || activeQuery.length < 2 || !savedName.trim()) return;
    try {
      const saved = await saveArtifactSearch({
        project_id: selectedProject.id,
        name: savedName.trim(),
        query: activeQuery,
        mode: activeMode,
        entity_type: activeEntityType || undefined,
      });
      setSavedSearches((current) => [...current.filter((item) => item.id !== saved.id), saved]
        .sort((left, right) => left.name.localeCompare(right.name)));
      setSavedName('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to save search');
    }
  }

  function applySavedSearch(saved: SavedSearch) {
    const next = new URLSearchParams({ q: saved.query, mode: saved.mode });
    if (saved.entity_type) next.set('type', saved.entity_type);
    setSearchParams(next, { replace: true });
  }

  function submitJudgment(result: SemanticSearchResult, judgment: 'clicked' | 'relevant' | 'not_relevant') {
    const eventId = result.metadata.search_event_id;
    const rank = Number(result.metadata.result_rank);
    if (typeof eventId !== 'string' || !Number.isFinite(rank)) return;
    void recordSearchJudgment({
      search_event_id: eventId,
      entity_type: result.entity_type,
      entity_id: result.entity_id,
      rank,
      judgment,
    });
  }

  return (
    <main className="page-container">
      <header className="page-header">
        <div>
          <p className="eyebrow">Project-scoped retrieval</p>
          <h1>Search</h1>
          <p>Find requirements, approved test cases, and feedback by exact language, meaning, or both.</p>
        </div>
      </header>

      {error ? <div className="status-message status-error" role="alert">{error}</div> : null}
      <section className="detail-card search-panel">
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
              placeholder="REQ-142, expired token, audit trail..."
            />
          </label>

          <fieldset className="search-mode-fieldset">
            <legend>Search mode</legend>
            <div className="search-mode-grid">
              {searchModes.map((option) => (
                <label className={`search-mode-option ${mode === option.value ? 'selected' : ''}`} key={option.value}>
                  <input
                    type="radio"
                    name="search-mode"
                    value={option.value}
                    checked={mode === option.value}
                    onChange={() => setMode(option.value)}
                  />
                  <span>
                    <strong>{option.label}</strong>
                    {option.value === 'hybrid' ? <small className="recommended-label">Recommended</small> : null}
                    <small>{option.description}</small>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>

          <div className="search-form-actions">
            <label>
              Artifact type
              <select value={entityType} onChange={(event) => setEntityType(event.target.value as typeof entityType)}>
                <option value="">All indexed artifacts</option>
                <option value="requirement">Requirements</option>
                <option value="test_case">Approved test cases</option>
                <option value="feedback">Feedback</option>
              </select>
            </label>
            <label>
              Custom field
              <input
                value={customField}
                onChange={(event) => setCustomField(event.target.value)}
                placeholder="risk"
                maxLength={100}
              />
            </label>
            <label>
              Custom value
              <input
                value={customValue}
                onChange={(event) => setCustomValue(event.target.value)}
                placeholder="high"
                maxLength={500}
                disabled={!customField.trim()}
              />
            </label>
            <button className="primary-button" type="submit" disabled={busy || !selectedProject || query.trim().length < 2}>
              {busy ? 'Searching...' : 'Search'}
            </button>
          </div>
        </form>
      </section>

      {activeQuery.length >= 2 ? (
        <section className="detail-card saved-search-panel">
          <label>
            Save this search
            <input
              value={savedName}
              onChange={(event) => setSavedName(event.target.value)}
              maxLength={255}
              placeholder="Regression candidates"
            />
          </label>
          <button type="button" className="secondary-button" onClick={handleSaveSearch} disabled={!savedName.trim()}>
            Save
          </button>
        </section>
      ) : null}
      {savedSearches.length ? (
        <nav className="saved-searches" aria-label="Saved searches">
          {savedSearches.map((saved) => (
            <button type="button" key={saved.id} onClick={() => applySavedSearch(saved)}>{saved.name}</button>
          ))}
        </nav>
      ) : null}

      <section className="history-list" aria-live="polite" aria-busy={busy}>
        {results.map((result) => {
          const requirementId = result.entity_type === 'requirement'
            ? result.entity_id
            : typeof result.metadata.requirement_id === 'string' ? result.metadata.requirement_id : null;
          return (
            <article className="history-card search-result-card" key={`${result.entity_type}:${result.entity_id}`}>
              <div className="detail-actions search-result-heading">
                <div className="detail-actions">
                  <span className="status-pill">{result.entity_type.replace('_', ' ')}</span>
                  <span className="search-method-pill">{result.search_mode}</span>
                </div>
                <span className="similarity-pill">
                  {result.search_mode === 'hybrid' ? 'Hybrid rank' : 'Relevance'} {percentage(result.score)}
                </span>
              </div>
              <h2>{result.title}</h2>
              <p>{result.text}</p>
              <div className="search-evidence" aria-label="Search evidence">
                {result.semantic_score !== undefined && result.semantic_score !== null ? (
                  <span>Semantic {percentage(result.semantic_score)}</span>
                ) : null}
                {result.keyword_score !== undefined && result.keyword_score !== null ? (
                  <span>Keyword {percentage(result.keyword_score)}</span>
                ) : null}
                {result.matched_fields.map((field) => <span key={field}>Matched {field}</span>)}
              </div>
              <div className="search-result-actions">
                {requirementId ? (
                  <Link onClick={() => submitJudgment(result, 'clicked')} to={`/requirements/${requirementId}`}>
                    Open requirement
                  </Link>
                ) : null}
                <button type="button" onClick={() => submitJudgment(result, 'relevant')}>Relevant</button>
                <button type="button" onClick={() => submitJudgment(result, 'not_relevant')}>Not relevant</button>
              </div>
            </article>
          );
        })}
        {!busy && activeQuery.length >= 2 && results.length === 0 && !error ? (
          <p>No {activeMode} results found for “{activeQuery}”.</p>
        ) : null}
        {!busy && activeQuery.length < 2 ? <p>Enter at least two characters to search.</p> : null}
        {hasMore ? (
          <button type="button" className="secondary-button" onClick={handleLoadMore} disabled={busy}>
            {busy ? 'Loading...' : 'Load more'}
          </button>
        ) : null}
      </section>
    </main>
  );
}
