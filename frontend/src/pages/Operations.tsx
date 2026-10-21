import { FormEvent, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  acknowledgeAlert,
  AlertSummary,
  cleanupRequirementText,
  CleanupResult,
  ComplianceEvidenceExport,
  ComplianceProfile,
  createSemanticCalibration,
  createGovernancePolicy,
  DependencyHealthSummary,
  EvaluationRunSummary,
  getGovernancePolicies,
  getAlerts,
  getComplianceProfile,
  getDependencyHealth,
  getMonitoringSummary,
  getOutboxEvents,
  getSemanticCalibrations,
  GovernancePolicySummary,
  importJiraRequirements,
  importHistoricalTestCases,
  createImportMappingProfile,
  executeMappedImport,
  getImportMappingProfiles,
  previewMappedImport,
  ImportMappingProfile,
  MappedImportPreview,
  importRequirementFile,
  IntegrationRunSummary,
  MonitoringSummary,
  OutboxEventSummary,
  RepositorySyncRunSummary,
  SemanticCalibrationSample,
  SemanticCalibrationSummary,
  ProjectSummary,
  runEvaluationSuite,
  retryOutboxEvent,
  syncTestRepository,
  updateComplianceProfile,
  exportComplianceEvidence,
} from '../api';

const STORY_MAPPING = {
  fields: {
    external_id: { source: 'key' },
    title: { source: 'summary' },
    description: {
      sources: ['description', 'acceptanceCriteria'],
      separator: '\n\nAcceptance criteria:\n',
    },
  },
  custom_fields: {
    status: 'status.name', priority: 'priority.name', project: 'project', epic: 'epic',
    risk: 'risk', labels: 'labels', components: 'components', source_type: 'sourceType',
  },
  options: {},
};

const TEST_CASE_MAPPING = {
  fields: {
    external_id: { source: 'id' },
    requirement_external_id: { source: 'linkedStories', transform: 'references' },
    scenario_external_id: { source: 'module' },
    scenario_title: { source: 'module' },
    scenario_description: { source: 'module' },
    title: { source: 'title' },
    description: { source: 'description' },
    prerequisite: { source: 'preRequisites' },
    priority: { source: 'priority' },
    severity: { source: 'risk' },
    category: { source: 'module' },
    type: { source: 'type' },
    status: { default: 'approved' },
    version: { source: 'version', transform: 'version_integer' },
    approved_at: { source: 'lastModifiedDate', transform: 'excel_datetime' },
    approved_by: { source: 'createdBy' },
    steps: { source: 'steps', transform: 'numbered_steps' },
  },
  custom_fields: {
    automation_manual: 'automationManual', created_by: 'createdBy', created_date: 'createdDate',
    last_modified_date: 'lastModifiedDate', module: 'module',
  },
  options: {
    expected_result_source: 'expectedResults',
    multi_requirement_strategy: 'duplicate',
    unresolved_reference_policy: 'skip',
  },
};

type OperationsPageProps = {
  selectedProject: ProjectSummary | null;
};

export default function OperationsPage({ selectedProject }: OperationsPageProps) {
  const [jiraJql, setJiraJql] = useState('ORDER BY updated DESC');
  const [repository, setRepository] = useState('enterprise-test-repository');
  const [branch, setBranch] = useState('main');
  const [cleanupText, setCleanupText] = useState('TBD user should validate checkout ASAP');
  const [policyName, setPolicyName] = useState('Default approval policy');
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [monitoring, setMonitoring] = useState<MonitoringSummary | null>(null);
  const [importRun, setImportRun] = useState<IntegrationRunSummary | null>(null);
  const [syncRun, setSyncRun] = useState<RepositorySyncRunSummary | null>(null);
  const [uploadRun, setUploadRun] = useState<IntegrationRunSummary | null>(null);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [historicalRun, setHistoricalRun] = useState<IntegrationRunSummary | null>(null);
  const [historicalFile, setHistoricalFile] = useState<File | null>(null);
  const [mappingProfiles, setMappingProfiles] = useState<ImportMappingProfile[]>([]);
  const [mappingEntity, setMappingEntity] = useState<'requirement' | 'test_case'>('requirement');
  const [mappingName, setMappingName] = useState('Company user stories');
  const [mappingConfig, setMappingConfig] = useState(JSON.stringify(STORY_MAPPING, null, 2));
  const [mappedProfileId, setMappedProfileId] = useState('');
  const [mappedFile, setMappedFile] = useState<File | null>(null);
  const [mappedPreview, setMappedPreview] = useState<MappedImportPreview | null>(null);
  const [mappedRun, setMappedRun] = useState<IntegrationRunSummary | null>(null);
  const [cleanupResult, setCleanupResult] = useState<CleanupResult | null>(null);
  const [evaluationRun, setEvaluationRun] = useState<EvaluationRunSummary | null>(null);
  const [policies, setPolicies] = useState<GovernancePolicySummary[]>([]);
  const [dependencies, setDependencies] = useState<DependencyHealthSummary | null>(null);
  const [outboxEvents, setOutboxEvents] = useState<OutboxEventSummary[]>([]);
  const [alerts, setAlerts] = useState<AlertSummary[]>([]);
  const [compliance, setCompliance] = useState<ComplianceProfile | null>(null);
  const [complianceExport, setComplianceExport] = useState<ComplianceEvidenceExport | null>(null);
  const [calibrations, setCalibrations] = useState<SemanticCalibrationSummary[]>([]);
  const [frameworks, setFrameworks] = useState('SOC2, ISO27001');
  const [retentionDays, setRetentionDays] = useState(365);
  const [approvalNotesRequired, setApprovalNotesRequired] = useState(false);
  const [calibrationData, setCalibrationData] = useState(JSON.stringify([
    { similarity: 0.96, expected_action: 'duplicate' },
    { similarity: 0.91, expected_action: 'duplicate' },
    { similarity: 0.86, expected_action: 'duplicate' },
    { similarity: 0.74, expected_action: 'update' },
    { similarity: 0.68, expected_action: 'update' },
    { similarity: 0.57, expected_action: 'update' },
    { similarity: 0.41, expected_action: 'unrelated' },
    { similarity: 0.30, expected_action: 'unrelated' },
    { similarity: 0.20, expected_action: 'unrelated' },
    { similarity: 0.10, expected_action: 'unrelated' },
  ], null, 2));

  const refreshOperations = async () => {
    try {
      setError(null);
      const [monitoringData, policyData, dependencyData, outboxData, alertData, complianceData, calibrationRuns] = await Promise.all([
        getMonitoringSummary(),
        getGovernancePolicies(),
        getDependencyHealth(),
        getOutboxEvents(),
        getAlerts(selectedProject?.id),
        selectedProject ? getComplianceProfile(selectedProject.id) : Promise.resolve(null),
        selectedProject ? getSemanticCalibrations(selectedProject.id) : Promise.resolve([]),
      ]);
      setMonitoring(monitoringData);
      setPolicies(policyData);
      setDependencies(dependencyData);
      setOutboxEvents(outboxData);
      setAlerts(alertData);
      setCompliance(complianceData);
      setCalibrations(calibrationRuns);
      if (complianceData) {
        setFrameworks(complianceData.frameworks.join(', '));
        setRetentionDays(complianceData.evidence_retention_days);
        setApprovalNotesRequired(complianceData.approval_notes_required);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load operations data');
    }
  };

  useEffect(() => {
    refreshOperations();
    if (selectedProject) {
      getImportMappingProfiles(selectedProject.id).then(setMappingProfiles).catch(() => setMappingProfiles([]));
    } else {
      setMappingProfiles([]);
    }
  }, [selectedProject?.id]);

  const changeMappingEntity = (entity: 'requirement' | 'test_case') => {
    setMappingEntity(entity);
    setMappingName(entity === 'requirement' ? 'Company user stories' : 'Company test cases');
    setMappingConfig(JSON.stringify(entity === 'requirement' ? STORY_MAPPING : TEST_CASE_MAPPING, null, 2));
  };

  const handleSaveMapping = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedProject) {
      setError('Select a project before saving an import mapping.');
      return;
    }
    runAction('save-mapping', async () => {
      const profile = await createImportMappingProfile({
        project_id: selectedProject.id,
        name: mappingName,
        entity_type: mappingEntity,
        configuration: JSON.parse(mappingConfig) as Record<string, unknown>,
        active: true,
      });
      setMappingProfiles((current) => [...current, profile]);
      setMappedProfileId(profile.id);
    });
  };

  const handleMappedPreview = () => {
    if (!mappedProfileId || !mappedFile) {
      setError('Choose a mapping profile and source file first.');
      return;
    }
    runAction('mapped-preview', async () => {
      setMappedPreview(await previewMappedImport(mappedProfileId, mappedFile));
    });
  };

  const handleMappedImport = () => {
    if (!mappedProfileId || !mappedFile) return;
    runAction('mapped-import', async () => {
      setMappedRun(await executeMappedImport(mappedProfileId, mappedFile));
    });
  };

  const runAction = async (name: string, action: () => Promise<void>) => {
    try {
      setBusy(name);
      setError(null);
      await action();
      await refreshOperations();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Operation failed');
    } finally {
      setBusy(null);
    }
  };

  const handleImport = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedProject) {
      setError('Select a project before importing Jira requirements.');
      return;
    }
    runAction('import', async () => {
      setImportRun(await importJiraRequirements(selectedProject.id, jiraJql));
    });
  };

  const handleFileImport = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedProject || !uploadFile) {
      setError('Select a project and requirement file before importing.');
      return;
    }
    runAction('file-import', async () => {
      setUploadRun(await importRequirementFile(selectedProject.id, uploadFile));
      setUploadFile(null);
    });
  };

  const handleHistoricalImport = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedProject || !historicalFile) {
      setError('Select a project and historical test-case file before importing.');
      return;
    }
    runAction('historical-import', async () => {
      setHistoricalRun(await importHistoricalTestCases(selectedProject.id, historicalFile));
      setHistoricalFile(null);
    });
  };

  const handleRetryOutbox = (eventId: string) => {
    runAction(`retry-${eventId}`, async () => {
      await retryOutboxEvent(eventId);
    });
  };

  const handleAcknowledgeAlert = (alertId: string) => {
    runAction(`ack-${alertId}`, async () => {
      await acknowledgeAlert(alertId);
    });
  };

  const handleSync = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedProject) {
      setError('Select a project before syncing approved test cases.');
      return;
    }
    runAction('sync', async () => {
      setSyncRun(await syncTestRepository(selectedProject.id, repository, branch));
    });
  };

  const handleCleanup = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    runAction('cleanup', async () => {
      setCleanupResult(await cleanupRequirementText(cleanupText));
    });
  };

  const handleEvaluation = () => {
    runAction('evaluation', async () => {
      setEvaluationRun(await runEvaluationSuite());
    });
  };

  const handlePolicy = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    runAction('policy', async () => {
      await createGovernancePolicy({
        name: policyName,
        policy_type: 'approval',
        created_by: 'system',
        rules: {
          required_role: 'approver',
          quality_score_minimum: 85,
          approved_cases_locked: true,
        },
      });
    });
  };

  const handleCompliance = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedProject) return;
    runAction('compliance', async () => {
      setCompliance(await updateComplianceProfile(selectedProject.id, {
        frameworks: frameworks.split(',').map((item) => item.trim()).filter(Boolean),
        evidence_retention_days: retentionDays,
        evidence_export_enabled: true,
        pseudonymize_actors: true,
        approval_notes_required: approvalNotesRequired,
      }));
    });
  };

  const handleEvidenceExport = () => {
    if (!selectedProject) return;
    runAction('evidence', async () => {
      setComplianceExport(await exportComplianceEvidence(selectedProject.id));
    });
  };

  const handleCalibration = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedProject) return;
    runAction('calibration', async () => {
      const parsed = JSON.parse(calibrationData) as SemanticCalibrationSample[];
      await createSemanticCalibration(selectedProject.id, parsed, true);
    });
  };

  return (
    <main className="page-container">
      <header className="page-header">
        <div>
          <p className="eyebrow">Enterprise operations</p>
          <h1>Integrations and governance</h1>
        </div>
        <Link className="secondary-button" to="/requirements">
          Requirements
        </Link>
      </header>

      {error ? <div className="status-message status-error">{error}</div> : null}

      <section className="ops-grid">
        <article className="detail-card">
          <h2>Configurable import mappings</h2>
          <p className="case-meta">
            Save project-specific JSON/CSV mappings. Unknown company fields are retained and included in semantic indexing.
          </p>
          <form onSubmit={handleSaveMapping}>
            <label>
              Artifact type
              <select value={mappingEntity} onChange={(event) => changeMappingEntity(event.target.value as 'requirement' | 'test_case')}>
                <option value="requirement">User story / requirement</option>
                <option value="test_case">Historical test case</option>
              </select>
            </label>
            <label>
              Mapping name
              <input value={mappingName} onChange={(event) => setMappingName(event.target.value)} required />
            </label>
            <label>
              Mapping configuration
              <textarea rows={16} value={mappingConfig} onChange={(event) => setMappingConfig(event.target.value)} required />
            </label>
            <button className="secondary-button" type="submit" disabled={!selectedProject || busy === 'save-mapping'}>
              {busy === 'save-mapping' ? 'Saving...' : 'Save mapping'}
            </button>
          </form>
          <hr />
          <label>
            Saved mapping
            <select value={mappedProfileId} onChange={(event) => { setMappedProfileId(event.target.value); setMappedPreview(null); }}>
              <option value="">Select mapping</option>
              {mappingProfiles.filter((profile) => profile.active).map((profile) => (
                <option key={profile.id} value={profile.id}>{profile.name} · {profile.entity_type.replace('_', ' ')}</option>
              ))}
            </select>
          </label>
          <label>
            Company JSON or CSV file
            <input type="file" accept=".json,.csv,application/json,text/csv" onChange={(event) => { setMappedFile(event.target.files?.[0] ?? null); setMappedPreview(null); }} />
          </label>
          <div className="detail-actions">
            <button className="secondary-button" type="button" onClick={handleMappedPreview} disabled={!mappedProfileId || !mappedFile || busy === 'mapped-preview'}>
              {busy === 'mapped-preview' ? 'Previewing...' : 'Preview mapping'}
            </button>
            <button className="primary-button" type="button" onClick={handleMappedImport} disabled={!mappedProfileId || !mappedFile || !mappedPreview || mappedPreview.error_count > 0 || busy === 'mapped-import'}>
              {busy === 'mapped-import' ? 'Importing...' : 'Import mapped data'}
            </button>
          </div>
          {mappedPreview ? (
            <p className="case-meta" role="status">
              Source {mappedPreview.source_record_count} · Mapped {mappedPreview.mapped_record_count} · Eligible{' '}
              {mappedPreview.valid_record_count} · Skipped {mappedPreview.skipped_record_count} · Warnings{' '}
              {mappedPreview.warning_count} · Errors {mappedPreview.error_count}
            </p>
          ) : null}
          {mappedRun ? <p className="case-meta" role="status">Import completed: {String(mappedRun.result.created_count ?? mappedRun.result.created_test_case_count ?? 0)} created</p> : null}
        </article>
        <article className="detail-card">
          <h2>Monitoring</h2>
          {monitoring ? (
            <div className="impact-summary-grid">
              {Object.entries(monitoring.metrics).map(([key, value]) => (
                <div className="history-card" key={key}>
                  <strong>{value}</strong>
                  <span>{key.replace(/_/g, ' ')}</span>
                </div>
              ))}
            </div>
          ) : (
            <p>No monitoring snapshot loaded.</p>
          )}
          <button className="secondary-button" type="button" onClick={refreshOperations}>
            Refresh
          </button>
        </article>

        <article className="detail-card">
          <h2>Historical test cases</h2>
          <p className="case-meta">
            JSON or CSV · Requirements must already exist · Destination: {selectedProject?.name ?? 'Select a project'}
          </p>
          <form onSubmit={handleHistoricalImport}>
            <label>
              Historical test-case file
              <input
                type="file"
                accept=".json,.csv,text/csv,application/json"
                onChange={(event) => setHistoricalFile(event.target.files?.[0] ?? null)}
                required
              />
            </label>
            <div className="detail-actions">
              <button
                className="primary-button"
                type="submit"
                disabled={busy === 'historical-import' || !selectedProject || !historicalFile}
              >
                {busy === 'historical-import' ? 'Importing...' : 'Import historical cases'}
              </button>
            </div>
          </form>
          {historicalRun ? (
            <p className="case-meta" role="status">
              Created {String(historicalRun.result.created_test_case_count ?? 0)} · Existing{' '}
              {String(historicalRun.result.existing_test_case_count ?? 0)} · Queued vectors{' '}
              {String(historicalRun.result.queued_vector_count ?? 0)}
            </p>
          ) : null}
        </article>

        <article className="detail-card">
          <h2>Dependency health</h2>
          <p className="case-meta" role="status">
            Overall: {dependencies?.status ?? 'checking'}
          </p>
          <div className="history-list">
            {dependencies?.dependencies.map((dependency) => (
              <div className="history-card" key={dependency.name}>
                <strong>{dependency.name.replace(/_/g, ' ')}</strong>
                <span className={`status-pill status-${dependency.status}`}>{dependency.status.replace(/_/g, ' ')}</span>
                {dependency.detail ? <p className="case-meta">{dependency.detail}</p> : null}
              </div>
            ))}
          </div>
        </article>

        <article className="detail-card">
          <h2>File import</h2>
          <p className="case-meta">UTF-8 TXT, Markdown, CSV, or JSON · Destination: {selectedProject?.name ?? 'Select a project'}</p>
          <form onSubmit={handleFileImport}>
            <label>
              Requirement file
              <input
                type="file"
                accept=".txt,.md,.csv,.json,text/plain,text/markdown,text/csv,application/json"
                onChange={(event) => setUploadFile(event.target.files?.[0] ?? null)}
                required
              />
            </label>
            <div className="detail-actions">
              <button
                className="primary-button"
                type="submit"
                disabled={busy === 'file-import' || !selectedProject || !uploadFile}
              >
                {busy === 'file-import' ? 'Importing...' : 'Import file'}
              </button>
            </div>
          </form>
          {uploadRun ? (
            <p className="case-meta" role="status">
              Created {String(uploadRun.result.created_count ?? 0)} · Existing {String(uploadRun.result.existing_count ?? 0)}
            </p>
          ) : null}
        </article>

        <article className="detail-card">
          <h2>Jira import</h2>
          <p className="case-meta">Destination: {selectedProject?.name ?? 'Select a project'}</p>
          <form onSubmit={handleImport}>
            <label>
              JQL query
              <textarea value={jiraJql} onChange={(event) => setJiraJql(event.target.value)} required />
            </label>
            <div className="detail-actions">
              <button className="primary-button" type="submit" disabled={busy === 'import' || !selectedProject}>
                {busy === 'import' ? 'Importing...' : 'Import Jira'}
              </button>
            </div>
          </form>
          {importRun ? <p className="case-meta">Imported: {String(importRun.result.imported_count ?? 0)}</p> : null}
        </article>

        <article className="detail-card">
          <h2>Repository sync</h2>
          <p className="case-meta">Project: {selectedProject?.name ?? 'Select a project'}</p>
          <form onSubmit={handleSync}>
            <label>
              Repository
              <input value={repository} onChange={(event) => setRepository(event.target.value)} required />
            </label>
            <label>
              Branch
              <input value={branch} onChange={(event) => setBranch(event.target.value)} required />
            </label>
            <div className="detail-actions">
              <button className="primary-button" type="submit" disabled={busy === 'sync' || !selectedProject}>
                {busy === 'sync' ? 'Syncing...' : 'Sync repository'}
              </button>
            </div>
          </form>
          {syncRun ? (
            <p className="case-meta">
              {syncRun.status === 'queued' ? 'Queued' : 'Synced'} {String(syncRun.details.queued_count ?? syncRun.synced_count)} cases
            </p>
          ) : null}
        </article>

        <article className="detail-card">
          <h2>NLP cleanup</h2>
          <form onSubmit={handleCleanup}>
            <label>
              Requirement text
              <textarea value={cleanupText} onChange={(event) => setCleanupText(event.target.value)} required />
            </label>
            <div className="detail-actions">
              <button className="primary-button" type="submit" disabled={busy === 'cleanup'}>
                {busy === 'cleanup' ? 'Cleaning...' : 'Clean text'}
              </button>
            </div>
          </form>
          {cleanupResult ? (
            <div className="history-card">
              <strong>Cleaned</strong>
              <p>{cleanupResult.cleaned_text}</p>
              <p className="case-meta">Issues: {cleanupResult.issues.length}</p>
            </div>
          ) : null}
        </article>

        <article className="detail-card">
          <h2>Evaluation</h2>
          <div className="detail-actions">
            <button className="primary-button" type="button" onClick={handleEvaluation} disabled={busy === 'evaluation'}>
              {busy === 'evaluation' ? 'Running...' : 'Run quality suite'}
            </button>
          </div>
          {evaluationRun ? (
            <div className="history-card">
              <strong>{evaluationRun.score}/100</strong>
              <p>{evaluationRun.status}</p>
            </div>
          ) : null}
        </article>

        <article className="detail-card">
          <h2>Governance policies</h2>
          <form onSubmit={handlePolicy}>
            <label>
              Policy name
              <input value={policyName} onChange={(event) => setPolicyName(event.target.value)} required />
            </label>
            <div className="detail-actions">
              <button className="primary-button" type="submit" disabled={busy === 'policy'}>
                {busy === 'policy' ? 'Saving...' : 'Create policy'}
              </button>
            </div>
          </form>
          <div className="history-list">
            {policies.map((policy) => (
              <div className="history-card" key={policy.id}>
                <strong>{policy.name}</strong>
                <p className="case-meta">
                  {policy.policy_type} · {policy.status}
                </p>
              </div>
            ))}
          </div>
        </article>

        <article className="detail-card">
          <h2>Project compliance</h2>
          <p className="case-meta">Controls and export evidence for {selectedProject?.name ?? 'a selected project'}.</p>
          <form onSubmit={handleCompliance}>
            <label>
              Frameworks
              <input value={frameworks} onChange={(event) => setFrameworks(event.target.value)} />
            </label>
            <label>
              Evidence retention days
              <input type="number" min="30" max="3650" value={retentionDays} onChange={(event) => setRetentionDays(Number(event.target.value))} />
            </label>
            <label>
              <input type="checkbox" checked={approvalNotesRequired} onChange={(event) => setApprovalNotesRequired(event.target.checked)} />
              Require approval notes
            </label>
            <div className="detail-actions">
              <button className="primary-button" type="submit" disabled={!selectedProject || busy === 'compliance'}>
                {busy === 'compliance' ? 'Saving...' : 'Save compliance profile'}
              </button>
              <button className="secondary-button" type="button" onClick={handleEvidenceExport} disabled={!selectedProject || busy === 'evidence'}>
                {busy === 'evidence' ? 'Exporting...' : 'Generate evidence export'}
              </button>
            </div>
          </form>
          {compliance ? <p className="case-meta">Active retention: {compliance.evidence_retention_days} days</p> : null}
          {complianceExport ? (
            <p className="case-meta" role="status">
              Evidence SHA-256: {complianceExport.sha256}
              {complianceExport.is_complete
                ? ' (complete)'
                : ` (truncated: ${complianceExport.truncated_sections.join(', ')})`}
            </p>
          ) : null}
        </article>

        <article className="detail-card">
          <h2>Semantic calibration</h2>
          <p className="case-meta">Apply thresholds from labeled similarity outcomes. Include all three actions and at least 10 samples.</p>
          <form onSubmit={handleCalibration}>
            <label>
              Labeled samples (JSON)
              <textarea value={calibrationData} onChange={(event) => setCalibrationData(event.target.value)} rows={12} required />
            </label>
            <button className="primary-button" type="submit" disabled={!selectedProject || busy === 'calibration'}>
              {busy === 'calibration' ? 'Calibrating...' : 'Calibrate and apply'}
            </button>
          </form>
          {calibrations[0] ? (
            <p className="case-meta">Latest: {calibrations[0].status} · macro F1 {calibrations[0].metrics.macro_f1}</p>
          ) : <p className="case-meta">No calibration evidence yet.</p>}
        </article>

        <article className="detail-card ops-span-full">
          <h2>Operational alerts</h2>
          <p className="case-meta">Execution failures and exhausted deliveries that need human attention.</p>
          <div className="history-list">
            {alerts.length ? alerts.map((alert) => (
              <div className="history-card" key={alert.id}>
                <div className="history-card-header">
                  <strong>{alert.title}</strong>
                  <span className={`status-pill status-${alert.severity}`}>{alert.severity}</span>
                </div>
                <p className="case-meta">
                  {alert.category.replace(/_/g, ' ')} · delivery {alert.delivery_status.replace(/_/g, ' ')}
                </p>
                <pre>{JSON.stringify(alert.details, null, 2)}</pre>
                {alert.status === 'open' ? (
                  <button
                    className="secondary-button"
                    type="button"
                    onClick={() => handleAcknowledgeAlert(alert.id)}
                    disabled={busy === `ack-${alert.id}`}
                  >
                    {busy === `ack-${alert.id}` ? 'Acknowledging...' : 'Acknowledge'}
                  </button>
                ) : <span className="status-pill status-completed">Acknowledged</span>}
              </div>
            )) : <p>No operational alerts found.</p>}
          </div>
        </article>

        <article className="detail-card ops-span-full">
          <h2>Outbox delivery</h2>
          <p className="case-meta">Recent indexing and repository delivery events. Failed events can be safely requeued.</p>
          <div className="history-list">
            {outboxEvents.length ? outboxEvents.map((item) => (
              <div className="history-card" key={item.id}>
                <strong>{item.event_type}</strong>
                <p className="case-meta">{item.status} · attempts {item.attempts} · {item.aggregate_type} {item.aggregate_id}</p>
                {item.last_error ? <p className="status-message status-error">{item.last_error}</p> : null}
                {item.status === 'failed' ? (
                  <button
                    className="secondary-button"
                    type="button"
                    onClick={() => handleRetryOutbox(item.id)}
                    disabled={busy === `retry-${item.id}`}
                  >
                    {busy === `retry-${item.id}` ? 'Requeuing...' : 'Retry event'}
                  </button>
                ) : null}
              </div>
            )) : <p>No outbox events found.</p>}
          </div>
        </article>
      </section>
    </main>
  );
}
