import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  generateRequirementDraft,
  getRequirementImpact,
  getRequirements,
  ProjectSummary,
  RequirementSummary,
} from '../api';

const statusOptions = ['draft', 'generated', 'reviewed', 'approved'] as const;

interface Props {
  selectedProject: ProjectSummary | null;
}

export default function RequirementDashboard({ selectedProject }: Props) {
  const [requirements, setRequirements] = useState<RequirementSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [activeRowAction, setActiveRowAction] = useState<{
    requirementId: string;
    action: 'generate' | 'impact';
  } | null>(null);
  const [openActionRequirementId, setOpenActionRequirementId] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState<string | undefined>(undefined);
  const [refreshTick, setRefreshTick] = useState(0);

  useEffect(() => {
    async function fetchRequirements() {
      if (!selectedProject) {
        setRequirements([]);
        setLoading(false);
        return;
      }

      try {
        setLoading(true);
        setError(null);
        const data = await getRequirements(search, status, selectedProject.id);
        setRequirements(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    }

    fetchRequirements();
  }, [search, status, selectedProject, refreshTick]);

  const handleGenerateTestCases = async (requirement: RequirementSummary) => {
    try {
      setOpenActionRequirementId(null);
      setActiveRowAction({ requirementId: requirement.id, action: 'generate' });
      setError(null);
      setActionMessage(null);
      const updatedRequirement = await generateRequirementDraft(requirement.id);
      setRequirements((current) =>
        current.map((item) => (item.id === updatedRequirement.id ? updatedRequirement : item)),
      );
      setActionMessage(`Generated test cases for "${requirement.title}".`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to generate test cases');
    } finally {
      setActiveRowAction(null);
    }
  };

  const handleRunImpactAnalysis = async (requirement: RequirementSummary) => {
    try {
      setOpenActionRequirementId(null);
      setActiveRowAction({ requirementId: requirement.id, action: 'impact' });
      setError(null);
      setActionMessage(null);
      const impact = await getRequirementImpact(requirement.id);
      setActionMessage(
        `Impact analysis complete for "${requirement.title}": ${impact.duplicates.length} duplicates, ${impact.deprecations.length} deprecations, ${impact.updates.length} updates.`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to run impact analysis');
    } finally {
      setActiveRowAction(null);
    }
  };

  return (
    <main className="page-container">
      <header className="page-header">
        <div>
          <p className="eyebrow">Enterprise AI Test Case Generator</p>
          <h1>{selectedProject ? `${selectedProject.name} Requirements` : 'Requirements'}</h1>
        </div>
        <div className="header-actions">
          <Link
            to="/requirements/new"
            className={selectedProject ? 'primary-button' : 'primary-button disabled-link'}
            aria-disabled={!selectedProject}
          >
            Add Requirement
          </Link>
        </div>
      </header>

      <section className="filter-bar rich-toolbar">
        <div className="search-control">
          <span className="search-prefix">Search</span>
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Requirements, IDs, descriptions"
          />
          {search ? (
            <button
              className="clear-control"
              type="button"
              onClick={() => setSearch('')}
              aria-label="Clear requirement search"
            >
              Clear
            </button>
          ) : null}
        </div>
        <div className="toolbar-controls">
          <div className="filter-actions segmented-control" aria-label="Requirement status filter">
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
          <span className="result-count">{requirements.length} shown</span>
          <button
            className="secondary-button refresh-control"
            type="button"
            onClick={() => setRefreshTick((current) => current + 1)}
            disabled={!selectedProject || loading}
          >
            Refresh
          </button>
        </div>
      </section>

      {loading ? (
        <div className="status-message">Loading requirements...</div>
      ) : error ? (
        <div className="status-message status-error">{error}</div>
      ) : !selectedProject ? (
        <div className="status-message">Create or select a project to view requirements.</div>
      ) : (
        <section className="table-panel" aria-label="Requirements">
          {actionMessage ? <div className="status-message status-success">{actionMessage}</div> : null}
          {requirements.length > 0 ? (
            <div className="table-scroll">
              <table className="data-table requirements-table">
                <thead>
                  <tr>
                    <th scope="col" className="requirement-column">
                      Requirement
                    </th>
                    <th scope="col" className="external-id-column">
                      External ID
                    </th>
                    <th scope="col" className="source-column">
                      Source
                    </th>
                    <th scope="col" className="status-column">
                      Status
                    </th>
                    <th scope="col" className="updated-column">
                      Updated
                    </th>
                    <th scope="col" className="actions-column requirement-actions-column">
                      Action
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {requirements.map((requirement) => (
                    <tr key={requirement.id}>
                      <td>
                        <strong>{requirement.title}</strong>
                        {requirement.description ? (
                          <span className="table-description">{requirement.description}</span>
                        ) : null}
                      </td>
                      <td>
                        <span className="cell-text">{requirement.external_id ?? '—'}</span>
                      </td>
                      <td>
                        <span className="chip">{requirement.source}</span>
                      </td>
                      <td>
                        <span className="status-pill">{requirement.status}</span>
                      </td>
                      <td>
                        <span className="cell-text">
                          {requirement.updated_at ? new Date(requirement.updated_at).toLocaleDateString() : '—'}
                        </span>
                      </td>
                      <td>
                        <div className="action-menu">
                          <button
                            className="icon-button"
                            type="button"
                            aria-label={`Actions for ${requirement.title}`}
                            aria-expanded={openActionRequirementId === requirement.id}
                            onClick={() =>
                              setOpenActionRequirementId((current) =>
                                current === requirement.id ? null : requirement.id,
                              )
                            }
                          >
                            <span className="kebab-icon" aria-hidden="true">
                              <span />
                              <span />
                              <span />
                            </span>
                          </button>
                          {openActionRequirementId === requirement.id ? (
                            <div className="action-menu-panel" role="menu">
                              <Link
                                to={`/requirements/${requirement.id}`}
                                className="action-menu-item"
                                role="menuitem"
                                onClick={() => setOpenActionRequirementId(null)}
                              >
                                View Requirements
                              </Link>
                              <button
                                className="action-menu-item"
                                type="button"
                                role="menuitem"
                                onClick={() => handleGenerateTestCases(requirement)}
                                disabled={
                                  activeRowAction?.requirementId === requirement.id &&
                                  activeRowAction.action === 'generate'
                                }
                              >
                                {activeRowAction?.requirementId === requirement.id &&
                                activeRowAction.action === 'generate'
                                  ? 'Generating...'
                                  : 'Generate Test cases'}
                              </button>
                              <button
                                className="action-menu-item"
                                type="button"
                                role="menuitem"
                                onClick={() => handleRunImpactAnalysis(requirement)}
                                disabled={
                                  activeRowAction?.requirementId === requirement.id &&
                                  activeRowAction.action === 'impact'
                                }
                              >
                                {activeRowAction?.requirementId === requirement.id &&
                                activeRowAction.action === 'impact'
                                  ? 'Running...'
                                  : 'Run impact analysis'}
                              </button>
                              <Link
                                to={`/requirements/${requirement.id}/test-cases`}
                                className="action-menu-item"
                                role="menuitem"
                                onClick={() => setOpenActionRequirementId(null)}
                              >
                                View test cases
                              </Link>
                            </div>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="status-message">No requirements found.</div>
          )}
        </section>
      )}
    </main>
  );
}
