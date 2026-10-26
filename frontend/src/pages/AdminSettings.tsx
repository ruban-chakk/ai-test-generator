import { FormEvent, useEffect, useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import BackLink from '../components/BackLink';
import SettingsHub, { SettingsDestination } from '../components/SettingsHub';
import {
  AdminContext, AICostSummary, AIModelConfiguration, AuthenticatedUser,
  AuditLogSummary,
  PromptConfiguration,
  PromptConfigurationVersion,
  createAdminUser, createInvitation, createOrganization, createProject,
  getAdminUsers, getAICostSummary, getModelConfiguration, getOrganizationMembers,
  getOrganizations, getProjectMembers, InvitationSummary, OrganizationSummary,
  ProjectSummary, getAudit, getEffectivePromptConfiguration, getPromptConfiguration, getPromptConfigurationHistory, putModelConfiguration, putOrganizationMember, putProjectMember, putPromptConfiguration,
  ScopedMembership, updateAdminUserRole,
} from '../api';

const defaultWeights = {
  requirement_coverage: 0.15, grounding: 0.15, correctness: 0.15,
  completeness: 0.12, relevance: 0.10, hallucination_rate: 0.07,
  executability: 0.10, boundary_and_negative_coverage: 0.08, traceability: 0.08,
};
const emptyModelConfig: AIModelConfiguration = {
  generation_model: 'gpt-5.4-mini', judge_model: 'gpt-5.4-mini',
  embedding_model: 'text-embedding-3-small', vector_provider: 'pinecone',
  vector_index: 'ai-testgen-embeddings-vectors', vector_namespace: 'ai-test-generator',
  evaluation_weights: defaultWeights, pricing: {
    'gpt-5.4-mini': { input_per_million: 0.75, output_per_million: 4.50 },
    'gpt-5.4': { input_per_million: 2.50, output_per_million: 15.00 },
    'text-embedding-3-small': { input_per_million: 0.02, output_per_million: 0 },
  },
};

function formatUsd(micros: number) {
  if (micros > 0 && micros < 100) return '<$0.0001';
  return `$${(micros / 1_000_000).toFixed(4)}`;
}

type Props = {
  context: AdminContext;
  projects: ProjectSummary[];
  selectedProject: ProjectSummary | null;
  onProjectCreated: (project: ProjectSummary) => Promise<void>;
};

export default function AdminSettings({ context, projects, selectedProject, onProjectCreated }: Props) {
  const section = useParams()['*'] ?? '';
  const [organizations, setOrganizations] = useState<OrganizationSummary[]>([]);
  const [users, setUsers] = useState<AuthenticatedUser[]>([]);
  const [members, setMembers] = useState<ScopedMembership[]>([]);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [costCenter, setCostCenter] = useState('unassigned');
  const [organizationId, setOrganizationId] = useState('');
  const [organizationName, setOrganizationName] = useState('');
  const [organizationSlug, setOrganizationSlug] = useState('');
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [globalRole, setGlobalRole] = useState<AuthenticatedUser['role']>('user');
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteProjectId, setInviteProjectId] = useState(selectedProject?.id ?? '');
  const [inviteOrgRole, setInviteOrgRole] = useState('member');
  const [inviteProjectRole, setInviteProjectRole] = useState('reviewer');
  const [invitation, setInvitation] = useState<InvitationSummary | null>(null);
  const [scopeType, setScopeType] = useState<'app' | 'organization' | 'project'>(context.is_app_admin ? 'app' : context.organization_admin_ids.length ? 'organization' : 'project');
  const [scopeId, setScopeId] = useState('');
  const [modelConfig, setModelConfig] = useState<AIModelConfiguration>(emptyModelConfig);
  const [weightsJson, setWeightsJson] = useState(JSON.stringify(defaultWeights, null, 2));
  const [pricingJson, setPricingJson] = useState(JSON.stringify(emptyModelConfig.pricing, null, 2));
  const [promptKey, setPromptKey] = useState<PromptConfiguration['prompt_key']>('test_case_generation');
  const [promptConfig, setPromptConfig] = useState<PromptConfiguration>({ prompt_key: 'test_case_generation', system_template: '', user_template: '', variables: [], temperature: 0.2, status: 'published' });
  const [promptHistory, setPromptHistory] = useState<PromptConfigurationVersion[]>([]);
  const [costs, setCosts] = useState<AICostSummary | null>(null);
  const [auditRows, setAuditRows] = useState<AuditLogSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const allowedOrganizations = useMemo(
    () => context.is_app_admin ? organizations : organizations.filter((item) => context.organization_admin_ids.includes(item.id)),
    [context, organizations],
  );
  const allowedProjects = useMemo(
    () => context.is_app_admin ? projects : projects.filter((item) => context.project_admin_ids.includes(item.id) || Boolean(item.organization_id && context.organization_admin_ids.includes(item.organization_id))),
    [context, projects],
  );
  const destinations: SettingsDestination[] = [
    ...(context.is_app_admin ? [{ key: 'organizations', title: 'Organizations', description: 'Create and govern tenant organizations', to: '/admin-settings/organizations', icon: 'governance' as const }] : []),
    { key: 'projects', title: 'Project administration', description: 'Create projects and assign cost centers', to: '/admin-settings/projects', icon: 'project' },
    ...(context.is_app_admin ? [{ key: 'users', title: 'Users', description: 'Create accounts and assign app roles', to: '/admin-settings/users', icon: 'project' as const }] : []),
    { key: 'roles', title: 'Scoped roles', description: 'Manage organization and project administrators', to: '/admin-settings/roles', icon: 'governance' },
    { key: 'invitations', title: 'Invitations', description: 'Invite users into an organization and project', to: '/admin-settings/invitations', icon: 'integration' },
    { key: 'models', title: 'AI & vector models', description: 'Generation, judge, embedding, and vector configuration', to: '/admin-settings/models', icon: 'calibration' },
    { key: 'prompts', title: 'Prompt templates', description: 'Scoped generation, feedback, and evaluation prompts', to: '/admin-settings/prompts', icon: 'calibration' },
    { key: 'costs', title: 'AI cost', description: 'Organization and project token-cost reporting', to: '/admin-settings/costs', icon: 'monitor' },
    { key: 'audit', title: 'Configuration audit', description: 'Review actor, timestamp, old value, and new value', to: '/admin-settings/audit', icon: 'governance' },
  ];
  const activeDestination = destinations.find((item) => item.key === section);

  useEffect(() => {
    getOrganizations().then((data) => {
      setOrganizations(data);
      setOrganizationId((current) => current || data[0]?.id || '');
    }).catch((err) => setError(err instanceof Error ? err.message : 'Unable to load organizations'));
  }, []);

  useEffect(() => {
    if (scopeType === 'app') setScopeId('');
    else if (scopeType === 'organization') setScopeId((current) => allowedOrganizations.some((item) => item.id === current) ? current : allowedOrganizations[0]?.id ?? '');
    else setScopeId((current) => allowedProjects.some((item) => item.id === current) ? current : allowedProjects[0]?.id ?? '');
  }, [scopeType, allowedOrganizations, allowedProjects]);

  const run = async (action: () => Promise<void>) => {
    setBusy(true); setError(null); setMessage(null);
    try { await action(); } catch (err) { setError(err instanceof Error ? err.message : 'Administration request failed'); }
    finally { setBusy(false); }
  };
  const loadUsers = async () => {
    const data = await getAdminUsers(context.is_app_admin ? undefined : allowedOrganizations[0]?.id, context.is_app_admin || allowedOrganizations.length ? undefined : allowedProjects[0]?.id);
    setUsers(data);
  };
  const loadMembers = async (type: 'organization' | 'project', id: string) => setMembers(type === 'organization' ? await getOrganizationMembers(id) : await getProjectMembers(id));
  const loadModelConfig = async () => {
    if (scopeType !== 'app' && !scopeId) return;
    const loaded = await getModelConfiguration(scopeType, scopeId || undefined) ?? emptyModelConfig;
    setModelConfig(loaded); setWeightsJson(JSON.stringify(loaded.evaluation_weights, null, 2)); setPricingJson(JSON.stringify(loaded.pricing, null, 2));
  };
  const loadCosts = async () => {
    if (scopeType === 'app' || !scopeId) return;
    setCosts(await getAICostSummary(scopeType, scopeId));
  };
  const loadAudit = async () => {
    const rows = await getAudit(undefined, undefined, scopeType, scopeId || undefined);
    setAuditRows(rows);
  };
  const loadPromptConfig = async () => {
    if (scopeType !== 'app' && !scopeId) return;
    const effectiveProjectId = scopeType === 'project' ? scopeId : selectedProject?.id;
    const loaded = effectiveProjectId
      ? await getEffectivePromptConfiguration(promptKey, effectiveProjectId, scopeType)
      : await getPromptConfiguration(promptKey, scopeType, scopeId || undefined);
    if (loaded) {
      setPromptConfig(loaded);
      // History follows the effective source, so inherited project/org views
      // show the versions that produced the prompt currently displayed.
      const historyScopeType = loaded.effective_scope_type && loaded.effective_scope_type !== 'built_in'
        ? loaded.effective_scope_type
        : scopeType;
      const historyScopeId = loaded.effective_scope_type && loaded.effective_scope_type !== 'built_in'
        ? loaded.effective_scope_id
        : scopeId || undefined;
      const history = await getPromptConfigurationHistory(promptKey, historyScopeType, historyScopeId);
      if (history.length || loaded.effective_scope_type !== 'built_in') {
        setPromptHistory(history);
      } else {
        // Built-in prompts are versioned as v0 even before an administrator
        // creates a scoped override, so the table is never mysteriously blank.
        setPromptHistory([{
          ...loaded,
          id: loaded.id || `builtin-${promptKey}`,
          prompt_configuration_id: loaded.id || `builtin-${promptKey}`,
          created_at: loaded.created_at || new Date(0).toISOString(),
          content_checksum: loaded.content_checksum || '',
          version: loaded.version ?? 0,
          status: loaded.status || 'published',
          scope_type: 'built_in',
          scope_id: undefined,
          change_notes: loaded.change_notes || 'Built-in default',
        }]);
      }
    } else {
      setPromptConfig({ prompt_key: promptKey, system_template: '', user_template: '', variables: [], temperature: 0.2, status: 'published' });
      setPromptHistory([]);
    }
  };

  useEffect(() => {
    if (section !== 'prompts' || (scopeType !== 'app' && !scopeId)) return;
    loadPromptConfig().catch((err) => setError(err instanceof Error ? err.message : 'Unable to load prompt configuration'));
  }, [section, promptKey, scopeType, scopeId, selectedProject?.id]);

  const scopePicker = (includeApp: boolean) => <div className="form-grid"><label>Scope<select value={includeApp ? scopeType : scopeType === 'app' ? 'organization' : scopeType} onChange={(event) => setScopeType(event.target.value as typeof scopeType)}>{includeApp && context.is_app_admin ? <option value="app">Application</option> : null}<option value="organization" disabled={!allowedOrganizations.length}>Organization</option><option value="project" disabled={!allowedProjects.length}>Project</option></select></label>{scopeType !== 'app' || !includeApp ? <label>Resource<select value={scopeId} onChange={(event) => setScopeId(event.target.value)}>{(scopeType === 'project' ? allowedProjects : allowedOrganizations).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label> : null}</div>;

  return <main className="page-container settings-page admin-settings-view">
    <header className="page-header"><div><p className="eyebrow">Governed administration</p><h1>{activeDestination?.title ?? 'Admin settings'}</h1><span className="header-subtitle">{activeDestination?.description ?? 'Administration is limited to your explicitly assigned scope.'}</span></div><BackLink to={section ? '/admin-settings' : '/requirements'} label={section ? 'All admin settings' : 'Back to workspace'} /></header>
    {error ? <div className="status-message status-error" role="alert">{error}</div> : null}{message ? <div className="status-message status-success" role="status">{message}</div> : null}
    {!section ? <SettingsHub destinations={destinations} label="Administration settings" /> : !activeDestination ? <div className="status-message status-error">Unknown administration setting.</div> : null}

    {section === 'organizations' && context.is_app_admin ? <section className="settings-section"><div className="section-heading"><div><h2>Organizations</h2><p>Only app administrators can create organization boundaries.</p></div></div><form className="form-grid" onSubmit={(event) => { event.preventDefault(); run(async () => { const created = await createOrganization({ name: organizationName, slug: organizationSlug }); setOrganizations((current) => [...current, created]); setOrganizationName(''); setOrganizationSlug(''); setMessage('Organization created.'); }); }}><label>Organization name<input value={organizationName} onChange={(event) => setOrganizationName(event.target.value)} required /></label><label>URL-safe slug<input value={organizationSlug} onChange={(event) => setOrganizationSlug(event.target.value.toLowerCase())} pattern="[a-z0-9][a-z0-9-]+[a-z0-9]" required /></label><div className="form-actions"><button className="primary-button" disabled={busy}>Create organization</button></div></form><div className="record-list">{organizations.map((organization) => <div key={organization.id}><div><strong>{organization.name}</strong><span>{organization.slug}</span></div><span>{organization.project_count} projects · {organization.member_count} members</span></div>)}</div></section> : null}

    {section === 'projects' ? <section className="settings-section admin-create-project"><div className="section-heading"><div><h2>Create project</h2><p>Projects belong to one organization and one accountable cost center.</p></div></div><form className="form-grid" onSubmit={(event) => { event.preventDefault(); run(async () => { const project = await createProject({ name: name.trim(), description: description.trim() || undefined, organization_id: organizationId, cost_center: costCenter, status: 'active' }); await onProjectCreated(project); setName(''); setDescription(''); setMessage(`Project “${project.name}” created and selected.`); }); }}><label>Organization<select value={organizationId} onChange={(event) => setOrganizationId(event.target.value)} required>{allowedOrganizations.map((organization) => <option key={organization.id} value={organization.id}>{organization.name}</option>)}</select></label><label>Cost center<input value={costCenter} onChange={(event) => setCostCenter(event.target.value)} required /></label><label>Project name<input value={name} onChange={(event) => setName(event.target.value)} required /></label><label className="span-full">Description<textarea rows={4} value={description} onChange={(event) => setDescription(event.target.value)} /></label><div className="form-actions"><button className="primary-button" disabled={busy || !name.trim() || !organizationId}>{busy ? 'Creating…' : 'Create project'}</button></div></form></section> : null}

    {section === 'users' && context.is_app_admin ? <section className="settings-section"><div className="section-heading"><div><h2>Application users</h2><p>App-admin assignment is restricted to existing app administrators.</p></div><button className="secondary-button" type="button" onClick={() => run(loadUsers)}>Refresh users</button></div><form className="form-grid" onSubmit={(event) => { event.preventDefault(); run(async () => { const created = await createAdminUser({ username, email, password, role: globalRole }); setUsers((current) => [...current, created]); setUsername(''); setEmail(''); setPassword(''); setMessage('User account created.'); }); }}><label>Username<input value={username} onChange={(event) => setUsername(event.target.value)} required /></label><label>Email<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required /></label><label>Temporary password<input type="password" minLength={12} value={password} onChange={(event) => setPassword(event.target.value)} required /></label><label>App role<select value={globalRole} onChange={(event) => setGlobalRole(event.target.value as AuthenticatedUser['role'])}><option value="user">User</option><option value="reviewer">Reviewer</option><option value="tester">Tester</option><option value="test_lead">Test lead</option><option value="product_manager">Product manager</option><option value="approver">Approver</option><option value="app_admin">App administrator</option></select></label><div className="form-actions"><button className="primary-button" disabled={busy}>Create user</button></div></form><div className="record-list">{users.map((item) => <div key={item.id}><div><strong>{item.username}</strong><span>{item.email}</span></div><select aria-label={`Role for ${item.username}`} value={item.role} onChange={(event) => run(async () => { const updated = await updateAdminUserRole(item.id, { role: event.target.value as AuthenticatedUser['role'], active: item.active }); setUsers((current) => current.map((entry) => entry.id === updated.id ? updated : entry)); setMessage('User role updated and sessions revoked.'); })}><option value="user">User</option><option value="reviewer">Reviewer</option><option value="tester">Tester</option><option value="test_lead">Test lead</option><option value="product_manager">Product manager</option><option value="approver">Approver</option><option value="app_admin">App administrator</option></select></div>)}{!users.length ? <p>Load users to manage app roles.</p> : null}</div></section> : null}

    {section === 'roles' ? <section className="settings-section"><div className="section-heading"><div><h2>Scoped administrator roles</h2><p>Organization and project roles never grant app-administrator permission.</p></div></div>{scopePicker(false)}<div className="form-actions"><button className="secondary-button" type="button" disabled={!scopeId || busy} onClick={() => run(() => loadMembers(scopeType === 'project' ? 'project' : 'organization', scopeId))}>Load role assignments</button></div><div className="record-list">{members.map((member) => <div key={member.id}><div><strong>{member.username}</strong><span>{member.email}</span></div><select aria-label={`Scoped role for ${member.username}`} value={member.role} onChange={(event) => run(async () => { const updated = scopeType === 'organization' ? await putOrganizationMember(scopeId, member.user_id, event.target.value) : await putProjectMember(scopeId, member.user_id, event.target.value); setMembers((current) => current.map((entry) => entry.id === updated.id ? updated : entry)); setMessage('Scoped role updated.'); })}>{scopeType === 'organization' ? <><option value="member">Member</option><option value="org_admin">Organization administrator</option></> : <><option value="reviewer">Reviewer</option><option value="tester">Tester</option><option value="test_lead">Test lead</option><option value="product_manager">Product manager</option><option value="approver">Approver</option><option value="project_admin">Project administrator</option></>}</select></div>)}</div></section> : null}

    {section === 'invitations' ? <section className="settings-section"><div className="section-heading"><div><h2>Invite user</h2><p>The invitation link is shown once; configure email delivery before production use.</p></div></div><form className="form-grid" onSubmit={(event) => { event.preventDefault(); run(async () => { const created = await createInvitation({ email: inviteEmail, organization_id: organizationId, project_id: inviteProjectId || undefined, organization_role: inviteOrgRole, project_role: inviteProjectId ? inviteProjectRole : undefined, expires_in_days: 7 }); setInvitation(created); setInviteEmail(''); setMessage('Invitation created.'); }); }}><label>Email<input type="email" value={inviteEmail} onChange={(event) => setInviteEmail(event.target.value)} required /></label><label>Organization<select value={organizationId} onChange={(event) => setOrganizationId(event.target.value)} required>{allowedOrganizations.map((organization) => <option key={organization.id} value={organization.id}>{organization.name}</option>)}</select></label><label>Organization role<select value={inviteOrgRole} onChange={(event) => setInviteOrgRole(event.target.value)}><option value="member">Member</option>{context.is_app_admin || context.organization_admin_ids.includes(organizationId) ? <option value="org_admin">Organization administrator</option> : null}</select></label><label>Project<select value={inviteProjectId} onChange={(event) => setInviteProjectId(event.target.value)}><option value="">No project</option>{allowedProjects.filter((project) => !organizationId || project.organization_id === organizationId).map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>{inviteProjectId ? <label>Project role<select value={inviteProjectRole} onChange={(event) => setInviteProjectRole(event.target.value)}><option value="reviewer">Reviewer</option><option value="tester">Tester</option><option value="test_lead">Test lead</option><option value="product_manager">Product manager</option><option value="approver">Approver</option><option value="project_admin">Project administrator</option></select></label> : null}<div className="form-actions"><button className="primary-button" disabled={busy}>Create invitation</button></div></form>{invitation?.invitation_token ? <div className="status-message"><strong>One-time invitation link</strong><code className="token-display">{window.location.origin}/accept-invitation/{invitation.invitation_token}</code><span>Expires {new Date(invitation.expires_at).toLocaleString()}</span></div> : null}</section> : null}

    {section === 'models' ? <section className="settings-section"><div className="section-heading"><div><h2>AI and vector configuration</h2><p>Prices are resolved by model ID. Built-in catalog prices apply automatically; scoped entries override them.</p></div><button className="secondary-button" type="button" disabled={busy || (scopeType !== 'app' && !scopeId)} onClick={() => run(loadModelConfig)}>Load configuration</button></div>{scopePicker(true)}<form className="form-grid" onSubmit={(event) => { event.preventDefault(); run(async () => { const saved = await putModelConfiguration(scopeType, scopeId || undefined, { ...modelConfig, evaluation_weights: JSON.parse(weightsJson), pricing: JSON.parse(pricingJson) }); setModelConfig(saved); setMessage('AI model configuration saved for this scope.'); }); }}><label>Generation model<input value={modelConfig.generation_model} onChange={(event) => setModelConfig({ ...modelConfig, generation_model: event.target.value })} required /></label><label>LLM-as-judge model<input value={modelConfig.judge_model} onChange={(event) => setModelConfig({ ...modelConfig, judge_model: event.target.value })} required /></label><label>Embedding model<input value={modelConfig.embedding_model} onChange={(event) => setModelConfig({ ...modelConfig, embedding_model: event.target.value })} required /></label><label>Vector index<input value={modelConfig.vector_index} onChange={(event) => setModelConfig({ ...modelConfig, vector_index: event.target.value })} required /></label><label>Vector namespace<input value={modelConfig.vector_namespace} onChange={(event) => setModelConfig({ ...modelConfig, vector_namespace: event.target.value })} required /></label><label>Vector host<input value={modelConfig.vector_host ?? ''} onChange={(event) => setModelConfig({ ...modelConfig, vector_host: event.target.value })} /></label><label className="span-full">Secret credential reference<input value={modelConfig.credential_reference ?? ''} onChange={(event) => setModelConfig({ ...modelConfig, credential_reference: event.target.value })} placeholder="secret://ai-test-generator/pinecone" /></label><label>DeepEval weights (JSON)<textarea className="code-input" rows={9} value={weightsJson} onChange={(event) => setWeightsJson(event.target.value)} /></label><label className="span-full">Model pricing catalog (JSON)<textarea className="code-input" rows={9} value={pricingJson} onChange={(event) => setPricingJson(event.target.value)} /><small>Use one entry per model: {`{"gpt-5.4":{"input_per_million":2.5,"output_per_million":15}}`}. Unknown models are reported as unpriced.</small></label><div className="form-actions"><button className="primary-button" disabled={busy}>Save configuration</button></div></form></section> : null}

    {section === 'prompts' ? <section className="settings-section"><div className="section-heading"><div><h2>Scoped prompt templates {promptConfig.version !== undefined ? <span className="metadata-badge">v{promptConfig.version}</span> : null}</h2><p>Project prompts override organization prompts, which override application defaults. Platform safety instructions remain enforced.</p>{promptConfig.effective_scope_type ? <p className="muted-text">Effective source: {promptConfig.effective_scope_type}{promptConfig.inherited ? ' (inherited)' : ' (local override)'}</p> : null}</div><button className="secondary-button" type="button" disabled={busy || (scopeType !== 'app' && !scopeId)} onClick={() => run(loadPromptConfig)}>Load prompt</button></div>{scopePicker(true)}<div className="form-grid"><label>Prompt purpose<select value={promptKey} onChange={(event) => setPromptKey(event.target.value as PromptConfiguration['prompt_key'])}><option value="test_case_generation">Test-case generation</option><option value="feedback_regeneration">Feedback regeneration</option><option value="test_case_evaluation">Test-case evaluation</option></select></label><label>Temperature<input type="number" min="0" max="2" step="0.1" value={promptConfig.temperature ?? 0} onChange={(event) => setPromptConfig({ ...promptConfig, temperature: Number(event.target.value) })} /></label><label className="span-full">Declared variables (comma separated)<input value={promptConfig.variables.join(', ')} onChange={(event) => setPromptConfig({ ...promptConfig, variables: event.target.value.split(',').map((item) => item.trim()).filter(Boolean) })} placeholder="external_id, source_text, context_text" /></label><label className="span-full">System template<textarea className="code-input" rows={9} value={promptConfig.system_template} onChange={(event) => setPromptConfig({ ...promptConfig, system_template: event.target.value })} required /></label><label className="span-full">User template<textarea className="code-input" rows={12} value={promptConfig.user_template} onChange={(event) => setPromptConfig({ ...promptConfig, user_template: event.target.value })} required /></label><div className="form-actions"><button className="primary-button" disabled={busy || !promptConfig.system_template || !promptConfig.user_template} onClick={() => run(async () => { const saved = await putPromptConfiguration(promptKey, scopeType, scopeId || undefined, { ...promptConfig, prompt_key: promptKey, status: 'published' }); setPromptConfig(saved); setPromptHistory(await getPromptConfigurationHistory(promptKey, scopeType, scopeId || undefined)); setMessage(`Prompt v${saved.version} saved for this scope.`); })}>Save prompt</button></div></div><div className="table-panel"><div className="section-heading"><div><h3>Version history</h3><p>Newest versions appear first.</p></div></div><table className="data-table"><thead><tr><th>Version</th><th>Status</th><th>Changed</th><th>Checksum</th><th>Change notes</th></tr></thead><tbody>{promptHistory.map((version) => <tr key={version.id}><td><span className="metadata-badge">v{version.version}</span></td><td>{version.status}</td><td>{new Date(version.created_at).toLocaleString()}</td><td><code>{version.content_checksum.slice(0, 12)}…</code></td><td>{version.change_notes || '—'}</td></tr>)}</tbody></table>{!promptHistory.length ? <p className="status-message">No saved versions exist for this scope yet.</p> : null}</div></section> : null}

    {section === 'costs' ? <section className="settings-section"><div className="section-heading"><div><h2>AI cost reporting</h2><p>Costs use recorded provider tokens and the rate snapshot captured for each call.</p></div></div>{scopePicker(false)}<div className="form-actions"><button className="primary-button" type="button" disabled={busy || !scopeId} onClick={() => run(loadCosts)}>Load cost report</button></div>{costs ? <>{costs.unpriced_models.length ? <div className="status-message status-warning" role="alert">Pricing is missing for: {costs.unpriced_models.join(', ')}. Configure rates under AI &amp; vector models.</div> : null}<dl className="definition-grid"><div><dt>Total cost</dt><dd>{formatUsd(costs.total_cost_micros)}</dd></div><div><dt>Input tokens</dt><dd>{costs.total_input_tokens.toLocaleString()}</dd></div><div><dt>Output tokens</dt><dd>{costs.total_output_tokens.toLocaleString()}</dd></div></dl><div className="table-panel"><table className="data-table"><thead><tr><th>Model</th><th>Input</th><th>Output</th><th>Pricing source</th><th>Cost</th></tr></thead><tbody>{costs.by_model.map((row) => <tr key={row.model}><td>{row.model}</td><td>{row.input_tokens.toLocaleString()}</td><td>{row.output_tokens.toLocaleString()}</td><td>{row.pricing_sources.join(', ').replace(/_/g, ' ')}</td><td>{formatUsd(row.cost_micros)}</td></tr>)}</tbody></table></div></> : <div className="status-message">Choose a scope to load its recorded AI cost.</div>}</section> : null}

    {section === 'audit' ? <section className="settings-section"><div className="section-heading"><div><h2>Configuration audit</h2><p>Every configuration change is recorded transactionally with its actor, timestamp, previous value, and resulting value.</p></div></div>{scopePicker(true)}<div className="form-actions"><button className="primary-button" type="button" disabled={busy || (scopeType !== 'app' && !scopeId)} onClick={() => run(loadAudit)}>Load audit history</button></div><div className="table-panel"><table className="data-table"><thead><tr><th>When</th><th>Actor</th><th>Action</th><th>Entity</th><th>Old value</th><th>New value</th></tr></thead><tbody>{auditRows.map((row) => <tr key={row.id}><td>{new Date(row.created_at).toLocaleString()}</td><td>{row.actor}</td><td>{row.action}</td><td>{row.entity_type}</td><td><code>{JSON.stringify(row.details?.old_value ?? null)}</code></td><td><code>{JSON.stringify(row.details?.new_value ?? null)}</code></td></tr>)}</tbody></table>{!auditRows.length ? <p className="status-message">No audit entries loaded for this scope.</p> : null}</div></section> : null}
  </main>;
}
