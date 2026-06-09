import { FormEvent, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  createScenarioForRequirement,
  createTestCaseForScenario,
  generateRequirementDraft,
  getRequirement,
  RequirementDetail,
} from '../api';

const defaultScenarioValues = {
  title: '',
  description: '',
  priority: 'medium',
  severity: 'major',
  category: 'functional',
  type: 'regression',
};

const defaultTestCaseValues = {
  title: '',
  description: '',
  prerequisite: '',
  priority: 'medium',
  severity: 'major',
  category: 'functional',
  type: 'regression',
};

export default function RequirementDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [requirement, setRequirement] = useState<RequirementDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [scenarioForm, setScenarioForm] = useState(defaultScenarioValues);
  const [scenarioSaving, setScenarioSaving] = useState(false);

  const [activeTestCaseScenarioId, setActiveTestCaseScenarioId] = useState<string | null>(null);
  const [testCaseForm, setTestCaseForm] = useState(defaultTestCaseValues);
  const [testCaseSaving, setTestCaseSaving] = useState(false);

  useEffect(() => {
    if (!id) {
      setError('Requirement ID is missing');
      setLoading(false);
      return;
    }

    async function fetchRequirement() {
      try {
        setLoading(true);
        setError(null);
        const requirementId = id as string;
        const data = await getRequirement(requirementId);
        setRequirement(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unable to load requirement');
      } finally {
        setLoading(false);
      }
    }

    fetchRequirement();
  }, [id]);

  const handleGenerateDraft = async () => {
    if (!id) {
      setError('Requirement ID is missing');
      return;
    }

    try {
      setSaving(true);
      setError(null);
      const data = await generateRequirementDraft(id);
      setRequirement(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to generate draft');
    } finally {
      setSaving(false);
    }
  };

  const handleScenarioChange = (field: string, value: string) => {
    setScenarioForm((current) => ({ ...current, [field]: value }));
  };

  const handleCreateScenario = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    if (!id) {
      setError('Requirement ID is missing');
      return;
    }

    try {
      setScenarioSaving(true);
      setError(null);
      const newScenario = await createScenarioForRequirement(id, scenarioForm);
      setRequirement((current) =>
        current
          ? {
              ...current,
              scenarios: [...(current.scenarios ?? []), newScenario],
            }
          : current,
      );
      setScenarioForm(defaultScenarioValues);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to create scenario');
    } finally {
      setScenarioSaving(false);
    }
  };

  const handleTestCaseChange = (field: string, value: string) => {
    setTestCaseForm((current) => ({ ...current, [field]: value }));
  };

  const handleCreateTestCase = async (event: FormEvent<HTMLFormElement>, scenarioId: string) => {
    event.preventDefault();

    try {
      setTestCaseSaving(true);
      setError(null);
      const newTestCase = await createTestCaseForScenario(scenarioId, testCaseForm);
      setRequirement((current) =>
        current
          ? {
              ...current,
              scenarios: current.scenarios?.map((scenario) =>
                scenario.id === scenarioId
                  ? {
                      ...scenario,
                      test_cases: [...(scenario.test_cases ?? []), newTestCase],
                    }
                  : scenario,
              ),
            }
          : current,
      );
      setTestCaseForm(defaultTestCaseValues);
      setActiveTestCaseScenarioId(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to create test case');
    } finally {
      setTestCaseSaving(false);
    }
  };

  return (
    <main className="page-container">
      <header className="page-header">
        <div>
          <p className="eyebrow">Requirement detail</p>
          <h1>{requirement?.title ?? 'Requirement details'}</h1>
        </div>
        <button className="secondary-button" onClick={() => navigate('/requirements')}>
          Back to list
        </button>
      </header>

      {loading ? (
        <div className="status-message">Loading requirement...</div>
      ) : error ? (
        <div className="status-message status-error">{error}</div>
      ) : requirement ? (
        <section className="detail-grid">
          <div className="detail-panel">
            <div className="detail-row">
              <span className="detail-label">ID</span>
              <span>{requirement.id}</span>
            </div>
            <div className="detail-row">
              <span className="detail-label">External ID</span>
              <span>{requirement.external_id ?? '—'}</span>
            </div>
            <div className="detail-row">
              <span className="detail-label">Source</span>
              <span>{requirement.source}</span>
            </div>
            <div className="detail-row">
              <span className="detail-label">Status</span>
              <span>{requirement.status}</span>
            </div>
            <div className="detail-row">
              <span className="detail-label">Created</span>
              <span>{requirement.created_at ? new Date(requirement.created_at).toLocaleString() : '—'}</span>
            </div>
            <div className="detail-row">
              <span className="detail-label">Updated</span>
              <span>{requirement.updated_at ? new Date(requirement.updated_at).toLocaleString() : '—'}</span>
            </div>
            <div className="detail-row detail-actions">
              <button className="primary-button" onClick={handleGenerateDraft} disabled={saving}>
                {saving ? 'Generating…' : 'Generate Draft'}
              </button>
            </div>
          </div>

          <article className="detail-card">
            <h2>Description</h2>
            <p>{requirement.description}</p>
          </article>

          <article className="detail-card">
            <h2>Add a new scenario</h2>
            <form onSubmit={handleCreateScenario}>
              <label>
                Title
                <input
                  type="text"
                  value={scenarioForm.title}
                  onChange={(event) => handleScenarioChange('title', event.target.value)}
                  required
                />
              </label>
              <label>
                Description
                <textarea
                  value={scenarioForm.description}
                  onChange={(event) => handleScenarioChange('description', event.target.value)}
                  required
                />
              </label>
              <div className="detail-actions">
                <button className="primary-button" type="submit" disabled={scenarioSaving}>
                  {scenarioSaving ? 'Saving…' : 'Create Scenario'}
                </button>
              </div>
            </form>
          </article>

          <article className="detail-card">
            <h2>Scenarios</h2>
            {requirement.scenarios?.length ? (
              requirement.scenarios.map((scenario) => (
                <div key={scenario.id} className="scenario-card">
                  <div className="scenario-header">
                    <div>
                      <h3>{scenario.title}</h3>
                      <p>{scenario.description}</p>
                    </div>
                    <button
                      className="secondary-button"
                      type="button"
                      onClick={() =>
                        setActiveTestCaseScenarioId((current) =>
                          current === scenario.id ? null : scenario.id,
                        )
                      }
                    >
                      {activeTestCaseScenarioId === scenario.id ? 'Cancel' : 'Add Test Case'}
                    </button>
                  </div>
                  <p className="scenario-meta">
                    {scenario.type} · {scenario.severity} · {scenario.status}
                  </p>

                  {activeTestCaseScenarioId === scenario.id && (
                    <form onSubmit={(event) => handleCreateTestCase(event, scenario.id)}>
                      <label>
                        Test case title
                        <input
                          type="text"
                          value={testCaseForm.title}
                          onChange={(event) => handleTestCaseChange('title', event.target.value)}
                          required
                        />
                      </label>
                      <label>
                        Description
                        <textarea
                          value={testCaseForm.description}
                          onChange={(event) => handleTestCaseChange('description', event.target.value)}
                          required
                        />
                      </label>
                      <label>
                        Prerequisite
                        <input
                          type="text"
                          value={testCaseForm.prerequisite}
                          onChange={(event) => handleTestCaseChange('prerequisite', event.target.value)}
                        />
                      </label>
                      <div className="detail-actions">
                        <button className="primary-button" type="submit" disabled={testCaseSaving}>
                          {testCaseSaving ? 'Saving…' : 'Create Test Case'}
                        </button>
                      </div>
                    </form>
                  )}

                  {scenario.test_cases?.length ? (
                    <div className="case-list">
                      {scenario.test_cases.map((testCase) => (
                        <div key={testCase.id} className="case-card">
                          <h4>{testCase.title}</h4>
                          <p>{testCase.description}</p>
                          <p className="case-meta">
                            {testCase.type} · {testCase.severity} · {testCase.status}
                          </p>
                          {testCase.steps?.map((step) => (
                            <div key={step.step_number} className="case-step">
                              <strong>Step {step.step_number}:</strong> {step.action}
                              <div className="expected-result">Expected: {step.expected_result}</div>
                            </div>
                          ))}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p>No test cases created yet for this scenario.</p>
                  )}
                </div>
              ))
            ) : (
              <p>No scenarios available yet.</p>
            )}
          </article>
        </section>
      ) : (
        <div className="status-message">Requirement not found.</div>
      )}
    </main>
  );
}
