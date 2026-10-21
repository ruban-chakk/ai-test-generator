import { FormEvent, useEffect, useMemo, useState } from 'react';
import { NavLink, Route, Routes, Navigate } from 'react-router-dom';
import RequirementDashboard from './pages/RequirementDashboard';
import RequirementDetail from './pages/RequirementDetail';
import RequirementTestCases from './pages/RequirementTestCases';
import RequirementCreate from './pages/RequirementCreate';
import Operations from './pages/Operations';
import SemanticSearch from './pages/SemanticSearch';
import Executions from './pages/Executions';
import {
  AuthenticatedUser,
  createProject,
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
  const [projectName, setProjectName] = useState('');
  const [projectDescription, setProjectDescription] = useState('');
  const [projectLoading, setProjectLoading] = useState(true);
  const [projectSaving, setProjectSaving] = useState(false);
  const [projectError, setProjectError] = useState<string | null>(null);

  const selectedProject = useMemo(
    () => projects.find((project) => project.id === selectedProjectId) ?? null,
    [projects, selectedProjectId],
  );

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
  }, [user]);

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
    }
  }

  function handleProjectChange(projectId: string) {
    setSelectedProjectId(projectId);
    localStorage.setItem(selectedProjectStorageKey, projectId);
  }

  async function handleProjectCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!projectName.trim()) return;

    try {
      setProjectSaving(true);
      setProjectError(null);
      const project = await createProject({
        name: projectName.trim(),
        description: projectDescription.trim() || undefined,
        status: 'active',
      });
      setProjectName('');
      setProjectDescription('');
      await refreshProjects(project.id);
    } catch (err) {
      setProjectError(err instanceof Error ? err.message : 'Unable to create project');
    } finally {
      setProjectSaving(false);
    }
  }

  if (authLoading) {
    return <div className="auth-status">Checking your session...</div>;
  }

  if (!user) {
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
          <label htmlFor="projectSelect">Project</label>
          <select
            id="projectSelect"
            value={selectedProjectId}
            onChange={(event) => handleProjectChange(event.target.value)}
            disabled={projectLoading || projects.length === 0}
          >
            {projects.length === 0 ? (
              <option value="">No projects</option>
            ) : (
              projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))
            )}
          </select>
          {selectedProject ? (
            <p>
              {selectedProject.requirement_count} requirements · {selectedProject.test_case_count} test cases
            </p>
          ) : (
            <p>Create a project to begin.</p>
          )}

          {user.role === 'admin' ? <form className="project-create" onSubmit={handleProjectCreate}>
            <input
              type="text"
              value={projectName}
              onChange={(event) => setProjectName(event.target.value)}
              placeholder="New project name"
              aria-label="New project name"
            />
            <textarea
              value={projectDescription}
              onChange={(event) => setProjectDescription(event.target.value)}
              placeholder="Description"
              aria-label="New project description"
              rows={3}
            />
            <button type="submit" className="secondary-button" disabled={projectSaving || !projectName.trim()}>
              {projectSaving ? 'Creating...' : 'Create Project'}
            </button>
          </form> : null}
          {projectError ? <div className="sidebar-error">{projectError}</div> : null}
        </section>

        <nav className="sidebar-nav" aria-label="Primary navigation">
          <NavLink to="/requirements" end>
            Requirements
          </NavLink>
          <NavLink to="/requirements/new">
            New Requirement
          </NavLink>
          <NavLink to="/search">Search</NavLink>
          <NavLink to="/executions">Executions</NavLink>
          {user.role === 'admin' ? <NavLink to="/operations">Operations</NavLink> : null}
        </nav>

        <div className="sidebar-user">
          <span>{user.username}</span>
          <small>{user.role}</small>
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
          <Route
            path="/requirements/new"
            element={<RequirementCreate selectedProject={selectedProject} />}
          />
          <Route path="/requirements/:id" element={<RequirementDetail />} />
          <Route path="/requirements/:id/test-cases" element={<RequirementTestCases />} />
          <Route path="/search" element={<SemanticSearch selectedProject={selectedProject} />} />
          <Route
            path="/executions"
            element={<Executions selectedProject={selectedProject} canExecute={user.role !== 'reviewer'} />}
          />
          <Route
            path="/operations"
            element={user.role === 'admin' ? <Operations selectedProject={selectedProject} /> : <Navigate to="/requirements" replace />}
          />
        </Routes>
      </section>
    </div>
  );
}

export default App;
