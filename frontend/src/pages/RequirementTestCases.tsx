import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { getRequirement, RequirementDetail } from '../api';

export default function RequirementTestCases() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [requirement, setRequirement] = useState<RequirementDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedScenarios, setExpandedScenarios] = useState<Set<string>>(new Set());
  const [expandedTestCases, setExpandedTestCases] = useState<Set<string>>(new Set());

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
        const data = await getRequirement(id as string);
        setRequirement(data);
        setExpandedScenarios(new Set(data.scenarios?.map((scenario) => scenario.id) ?? []));
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unable to load generated test cases');
      } finally {
        setLoading(false);
      }
    }

    fetchRequirement();
  }, [id]);

  const toggleScenario = (scenarioId: string) => {
    setExpandedScenarios((current) => {
      const next = new Set(current);
      if (next.has(scenarioId)) {
        next.delete(scenarioId);
      } else {
        next.add(scenarioId);
      }
      return next;
    });
  };

  const toggleTestCase = (testCaseId: string) => {
    setExpandedTestCases((current) => {
      const next = new Set(current);
      if (next.has(testCaseId)) {
        next.delete(testCaseId);
      } else {
        next.add(testCaseId);
      }
      return next;
    });
  };

  return (
    <main className="page-container">
      <header className="page-header">
        <div>
          <p className="eyebrow">Generated test cases</p>
          <h1>{requirement?.title ?? 'Generated Test Cases'}</h1>
          {requirement ? <span className="header-subtitle">Requirement ID: {requirement.id}</span> : null}
        </div>
        <div className="header-actions">
          <button className="secondary-button" type="button" onClick={() => navigate('/requirements')}>
            Requirements
          </button>
          {requirement ? (
            <Link className="primary-button" to={`/requirements/${requirement.id}`}>
              View Requirement
            </Link>
          ) : null}
        </div>
      </header>

      {loading ? (
        <div className="status-message">Loading generated test cases...</div>
      ) : error ? (
        <div className="status-message status-error">{error}</div>
      ) : requirement ? (
        <section className="testcase-browser" aria-label="Generated test cases by scenario">
          {requirement.scenarios?.length ? (
            requirement.scenarios.map((scenario) => {
              const isScenarioExpanded = expandedScenarios.has(scenario.id);
              const testCases = scenario.test_cases ?? [];

              return (
                <article key={scenario.id} className="collapsible-card">
                  <button
                    className="collapsible-header"
                    type="button"
                    aria-expanded={isScenarioExpanded}
                    onClick={() => toggleScenario(scenario.id)}
                  >
                    <span className="collapse-indicator">{isScenarioExpanded ? '-' : '+'}</span>
                    <span>
                      <strong>{scenario.title}</strong>
                      <span className="table-description">
                        {scenario.description} · {testCases.length} test case{testCases.length === 1 ? '' : 's'}
                      </span>
                    </span>
                  </button>

                  {isScenarioExpanded ? (
                    <div className="collapsible-body">
                      {testCases.length ? (
                        <div className="testcase-list">
                          {testCases.map((testCase) => {
                            const isTestCaseExpanded = expandedTestCases.has(testCase.id);
                            const steps = testCase.steps ?? [];

                            return (
                              <article key={testCase.id} className="testcase-item">
                                <button
                                  className="testcase-summary"
                                  type="button"
                                  aria-expanded={isTestCaseExpanded}
                                  onClick={() => toggleTestCase(testCase.id)}
                                >
                                  <span className="collapse-indicator">{isTestCaseExpanded ? '-' : '+'}</span>
                                  <span>
                                    <span className="testcase-id">Test ID: {testCase.id}</span>
                                    <strong>{testCase.title}</strong>
                                    <span className="table-description">{testCase.description}</span>
                                  </span>
                                </button>

                                {isTestCaseExpanded ? (
                                  <div className="table-scroll testcase-steps">
                                    {steps.length ? (
                                      <table className="data-table steps-table">
                                        <thead>
                                          <tr>
                                            <th scope="col">Step No</th>
                                            <th scope="col">Test Steps</th>
                                            <th scope="col">Expected Results</th>
                                          </tr>
                                        </thead>
                                        <tbody>
                                          {steps
                                            .slice()
                                            .sort((left, right) => left.step_number - right.step_number)
                                            .map((step) => (
                                              <tr key={step.step_number}>
                                                <td>{step.step_number}</td>
                                                <td>{step.action}</td>
                                                <td>{step.expected_result}</td>
                                              </tr>
                                            ))}
                                        </tbody>
                                      </table>
                                    ) : (
                                      <div className="status-message">No steps available for this test case.</div>
                                    )}
                                  </div>
                                ) : null}
                              </article>
                            );
                          })}
                        </div>
                      ) : (
                        <div className="status-message">No test cases generated for this scenario.</div>
                      )}
                    </div>
                  ) : null}
                </article>
              );
            })
          ) : (
            <div className="status-message">No test scenarios available for this requirement.</div>
          )}
        </section>
      ) : (
        <div className="status-message">Requirement not found.</div>
      )}
    </main>
  );
}
