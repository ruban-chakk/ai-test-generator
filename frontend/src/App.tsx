import { FormEvent, useEffect, useMemo, useState } from 'react';
import { NavLink, Route, Routes, Navigate } from 'react-router-dom';
import RequirementDashboard from './pages/RequirementDashboard';
import BulkOperationDashboard from './pages/BulkOperationDashboard';
import RequirementDetail from './pages/RequirementDetail';
import RequirementTestCases from './pages/RequirementTestCases';
import RequirementCreate from './pages/RequirementCreate';
import Operations from './pages/Operations';
import SemanticSearch from './pages/SemanticSearch';
import Executions from './pages/Executions';
import TestCaseDashboard from './pages/TestCaseDashboard';
import ProjectSettings from './pages/ProjectSettings';
import UserProfile from './pages/UserProfile';
import AdminSettings from './pages/AdminSettings';
import AcceptInvitation from './pages/AcceptInvitation';
import {
  AuthenticatedUser,
  AdminContext,
  getAdminContext,
  getAuthConfiguration,
  getCurrentUser,
  getProjects,
  login,
  logout,
  ProjectSummary,
} from './api';

const selectedProjectStorageKey = 'ai-test-generator:selected-project-id';

function App() {
  const [user, setUser] = useState<AuthenticatedUser | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authSaving, setAuthSaving] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);
  const [oidcLoginUrl, setOidcLoginUrl] = useState<string | null>(null);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string>('');
  const [projectSwitcherOpen, setProjectSwitcherOpen] = useState(false);
  const [projectLoading, setProjectLoading] = useState(true);
  const [projectError, setProjectError] = useState<string | null>(null);
  const [adminContext, setAdminContext] = useState<AdminContext | null>(null);

  const selectedProject = useMemo(
    () => projects.find((project) => project.id === selectedProjectId) ?? null,
    [projects, selectedProjectId],
  );

  useEffect(() => {
    const preferences = user?.settings_json;
    document.documentElement.dataset.theme = preferences?.theme ?? 'light';
    document.documentElement.dataset.density = preferences?.density ?? 'comfortable';
    document.documentElement.dataset.reduceMotion = String(preferences?.reduce_motion ?? false);
  }, [user]);

  async function refreshProjects(preferredProjectId?: string) {
    const data = await getProjects();
    setProjects(data);
    const storedProjectId = preferredProjectId ?? localStorage.getItem(selectedProjectStorageKey);
    const nextProject =
      data.find((project) => project.id === storedProjectId) ??
      data.find((project) => project.name.toLowerCase() === 'vms') ??
      data[0];
    if (nextProject) {
      setSelectedProjectId(nextProject.id);
      localStorage.setItem(selectedProjectStorageKey, nextProject.id);
    } else {
      setSelectedProjectId('');
      localStorage.removeItem(selectedProjectStorageKey);
    }
  }

  useEffect(() => {
    getAuthConfiguration()
      .then((configuration) => setOidcLoginUrl(configuration.oidc_enabled ? configuration.oidc_login_url ?? null : null))
      .catch(() => setOidcLoginUrl(null));
  }, []);

  useEffect(() => {
    async function restoreSession() {
      try {
        setUser(await getCurrentUser());
      } catch {
        setUser(null);
      } finally {
        setAuthLoading(false);
      }
    }
    restoreSession();
  }, []);

  useEffect(() => {
    if (!user) return;
    async function loadProjects() {
      try {
        setProjectLoading(true);
        setProjectError(null);
        await refreshProjects();
      } catch (err) {
        setProjectError(err instanceof Error ? err.message : 'Unable to load projects');
      } finally {
        setProjectLoading(false);
      }
    }
    loadProjects();
    getAdminContext().then(setAdminContext).catch(() => setAdminContext(null));
  }, [user]);

  useEffect(() => {
    if (!projectSwitcherOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setProjectSwitcherOpen(false);
    };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [projectSwitcherOpen]);

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      setAuthSaving(true);
      setAuthError(null);
      setUser(await login(username.trim(), password));
      setPassword('');
    } catch (err) {
      setAuthError(err instanceof Error ? err.message : 'Unable to sign in');
    } finally {
      setAuthSaving(false);
    }
  }

  async function handleLogout() {
    try {
      await logout();
    } finally {
      setUser(null);
      setProjects([]);
      setSelectedProjectId('');
      setAdminContext(null);
    }
  }

  function handleProjectChange(projectId: string) {
    setSelectedProjectId(projectId);
    localStorage.setItem(selectedProjectStorageKey, projectId);
    setProjectSwitcherOpen(false);
  }

  if (authLoading) {
    return <div className="auth-status">Checking your session...</div>;
  }

  if (!user) {
    const invitationMatch = window.location.pathname.match(/^\/accept-invitation\/([^/]+)$/);
    if (invitationMatch) return <AcceptInvitation token={decodeURIComponent(invitationMatch[1])} />;
    return (
      <main className="auth-shell">
        <form className="auth-card" onSubmit={handleLogin}>
          <span className="brand-mark">AI</span>
          <h1>Sign in to Test Generator</h1>
          <p>Use your enterprise QA account.</p>
          <label htmlFor="username">Username or email</label>
          <input
            id="username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoComplete="username"
            required
          />
          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
            required
          />
          {authError ? <div className="error-message">{authError}</div> : null}
          <button type="submit" disabled={authSaving}>
            {authSaving ? 'Signing in...' : 'Sign in'}
          </button>
          {oidcLoginUrl ? (
            <a className="secondary-button" href={oidcLoginUrl}>
              Sign in with enterprise SSO
            </a>
          ) : null}
        </form>
      </main>
    );
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <span className="brand-mark">AI</span>
          <div>
            <strong>Test Generator</strong>
            <span>Enterprise QA</span>
          </div>
        </div>

        <section className="project-panel" aria-label="Project selection">
          <span className="project-panel-label">Current project</span>
          <strong className="current-project-name">{selectedProject?.name ?? 'No project selected'}</strong>
          {selectedProject ? (
            <p>
              {selectedProject.requirement_count} requirements · {selectedProject.test_case_count} test cases
            </p>
          ) : (
            <p>Create a project to begin.</p>
          )}
          <button
            type="button"
            className="project-switch-button"
            onClick={() => setProjectSwitcherOpen(true)}
            disabled={projectLoading || projects.length === 0}
          >
            Switch project
          </button>
          {projectError ? <div className="sidebar-error">{projectError}</div> : null}
        </section>

        <nav className="sidebar-nav" aria-label="Primary navigation">
          <span className="nav-section-label">Workspace</span>
          <NavLink to="/requirements" end>
            Requirements
          </NavLink>
          <NavLink to="/operations/bulk-runs">Batch runs</NavLink>
          <NavLink to="/test-cases">Test Cases</NavLink>
          <NavLink to="/requirements/new">
            New Requirement
          </NavLink>
          <NavLink to="/search">Search</NavLink>
          <NavLink to="/executions">Executions</NavLink>
          <span className="nav-section-label">Administration</span>
          {selectedProject ? <NavLink to="/project-settings">Project Settings</NavLink> : null}
          {adminContext?.is_app_admin ? (
            <>
              <NavLink to="/operations">Operations</NavLink>
            </>
          ) : null}
          {adminContext && (adminContext.is_app_admin || adminContext.organization_admin_ids.length > 0 || adminContext.project_admin_ids.length > 0) ? <NavLink to="/admin-settings">Admin Settings</NavLink> : null}
        </nav>

        <div className="sidebar-user">
          <NavLink to="/profile" className="user-profile-link"><span className="user-avatar" aria-hidden="true">{user.username.slice(0, 2).toUpperCase()}</span><span><strong>{user.username}</strong><small>{user.role.replace('_', ' ')}</small></span></NavLink>
          <button type="button" className="secondary-button" onClick={handleLogout}>Sign out</button>
        </div>
      </aside>

      <section className="app-content">
        <Routes>
          <Route path="/" element={<Navigate to="/requirements" replace />} />
          <Route
            path="/requirements"
            element={<RequirementDashboard selectedProject={selectedProject} />}
          />
          <Route path="/operations/bulk-runs" element={<BulkOperationDashboard selectedProject={selectedProject} />} />
          <Route
            path="/requirements/new"
            element={<RequirementCreate selectedProject={selectedProject} />}
          />
          <Route path="/test-cases" element={<TestCaseDashboard selectedProject={selectedProject} />} />
          <Route path="/requirements/:id" element={<RequirementDetail />} />
          <Route path="/requirements/:id/test-cases" element={<RequirementTestCases user={user} />} />
          <Route path="/search" element={<SemanticSearch selectedProject={selectedProject} />} />
          <Route
            path="/executions"
            element={<Executions selectedProject={selectedProject} canExecute={user.role !== 'reviewer'} />}
          />
          <Route
            path="/operations/*"
            element={adminContext?.is_app_admin ? <Operations selectedProject={selectedProject} /> : <Navigate to="/requirements" replace />}
          />
          <Route path="/project-settings/*" element={<ProjectSettings selectedProject={selectedProject} user={user} canAdmin={Boolean(adminContext?.is_app_admin || (selectedProject && adminContext?.project_admin_ids.includes(selectedProject.id)) || (selectedProject?.organization_id && adminContext?.organization_admin_ids.includes(selectedProject.organization_id)))} onProjectChange={(updated) => setProjects((current) => current.map((project) => project.id === updated.id ? updated : project))} />} />
          <Route path="/admin-settings/*" element={adminContext ? <AdminSettings context={adminContext} projects={projects} selectedProject={selectedProject} onProjectCreated={async (project) => refreshProjects(project.id)} /> : <Navigate to="/requirements" replace />} />
          <Route path="/profile/*" element={<UserProfile user={user} onUserChange={setUser} />} />
        </Routes>
      </section>
      {projectSwitcherOpen ? (
        <div
          className="modal-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setProjectSwitcherOpen(false);
          }}
        >
          <div className="modal-panel project-switcher" role="dialog" aria-modal="true" aria-labelledby="switch-project-title">
            <div className="modal-header">
              <div>
                <p className="eyebrow">Workspace</p>
                <h2 id="switch-project-title">Switch project</h2>
              </div>
              <button type="button" className="secondary-button" onClick={() => setProjectSwitcherOpen(false)}>Close</button>
            </div>
            <div className="project-option-list">
              {projects.map((project) => (
                <button
                  type="button"
                  key={project.id}
                  className={project.id === selectedProjectId ? 'project-option active' : 'project-option'}
                  onClick={() => handleProjectChange(project.id)}
                >
                  <span>
                    <strong>{project.name}</strong>
                    <small>{project.description || 'No description'}</small>
                  </span>
                  <span>{project.requirement_count} requirements · {project.test_case_count} tests</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export default App;
