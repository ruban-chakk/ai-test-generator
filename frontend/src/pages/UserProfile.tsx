import { FormEvent, useState } from 'react';
import { useParams } from 'react-router-dom';
import BackLink from '../components/BackLink';
import SettingsHub, { SettingsDestination } from '../components/SettingsHub';
import { AuthenticatedUser, updateCurrentUser, updateUserSettings, UserPreferences } from '../api';

export default function UserProfile({ user, onUserChange }: { user: AuthenticatedUser; onUserChange: (user: AuthenticatedUser) => void }) {
  const section = useParams()['*'] ?? '';
  const [username, setUsername] = useState(user.username);
  const [email, setEmail] = useState(user.email);
  const [preferences, setPreferences] = useState<UserPreferences>({
    theme: user.settings_json?.theme ?? 'light', density: user.settings_json?.density ?? 'comfortable', reduce_motion: user.settings_json?.reduce_motion ?? false,
  });
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const destinations: SettingsDestination[] = [
    { key: 'profile', title: 'Profile', description: 'Identity used in reviews and audit records', to: '/profile/profile', icon: 'project' },
    { key: 'preferences', title: 'Workspace preferences', description: 'Theme, density, and motion preferences', to: '/profile/preferences', icon: 'calibration' },
    { key: 'access', title: 'Access', description: 'Role and account status', to: '/profile/access', icon: 'governance' },
  ];
  const activeDestination = destinations.find((item) => item.key === section);

  async function saveProfile(event: FormEvent) {
    event.preventDefault(); setBusy('profile'); setError(null);
    try { const updated = await updateCurrentUser({ username, email }); onUserChange(updated); setMessage('Profile updated.'); }
    catch (err) { setError(err instanceof Error ? err.message : 'Unable to update profile'); }
    finally { setBusy(null); }
  }
  async function savePreferences(event: FormEvent) {
    event.preventDefault(); setBusy('settings'); setError(null);
    try { const updated = await updateUserSettings(preferences); onUserChange(updated); setMessage('User settings saved.'); }
    catch (err) { setError(err instanceof Error ? err.message : 'Unable to save settings'); }
    finally { setBusy(null); }
  }

  return <main className={`page-container settings-page user-settings-view ${section ? `focused user-setting-${section}` : ''}`}>
    <header className="page-header"><div><p className="eyebrow">Account</p><h1>{activeDestination?.title ?? 'Profile & user settings'}</h1><span className="header-subtitle">{activeDestination?.description ?? 'Choose an account setting to manage.'}</span></div><BackLink to={section ? '/profile' : '/requirements'} label={section ? 'All user settings' : 'Back to workspace'} /></header>
    {error ? <div className="status-message status-error">{error}</div> : null}{message ? <div className="status-message status-success">{message}</div> : null}
    {!section ? <SettingsHub destinations={destinations} label="User settings" /> : !activeDestination ? <div className="status-message status-error">Unknown user setting.</div> : <div className="settings-content focused-settings">
      <section id="profile" className="settings-section"><div className="section-heading"><div><h2>Profile</h2><p>Your display identity across review and audit records.</p></div></div><form className="form-grid" onSubmit={saveProfile}><label>Username<input value={username} onChange={(event) => setUsername(event.target.value)} required /></label><label>Email<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required /></label><div className="form-actions"><button className="primary-button" disabled={busy === 'profile'}>{busy === 'profile' ? 'Saving…' : 'Save profile'}</button></div></form></section>
      <section id="preferences" className="settings-section"><div className="section-heading"><div><h2>Workspace preferences</h2><p>These settings follow your account across browsers.</p></div></div><form className="form-grid" onSubmit={savePreferences}><label>Theme<select value={preferences.theme} onChange={(event) => setPreferences({ ...preferences, theme: event.target.value as UserPreferences['theme'] })}><option value="light">Light</option><option value="dark">Dark</option><option value="system">Use system</option></select></label><label>Information density<select value={preferences.density} onChange={(event) => setPreferences({ ...preferences, density: event.target.value as UserPreferences['density'] })}><option value="comfortable">Comfortable</option><option value="compact">Compact</option></select></label><label className="checkbox-row"><input type="checkbox" checked={preferences.reduce_motion} onChange={(event) => setPreferences({ ...preferences, reduce_motion: event.target.checked })} /> Reduce interface motion</label><div className="form-actions"><button className="primary-button" disabled={busy === 'settings'}>{busy === 'settings' ? 'Saving…' : 'Save preferences'}</button></div></form></section>
      <section id="access" className="settings-section"><div className="section-heading"><div><h2>Access</h2><p>Global role and account status are controlled by an administrator.</p></div></div><dl className="definition-grid"><div><dt>Role</dt><dd>{user.role.replace('_', ' ')}</dd></div><div><dt>Status</dt><dd>{user.active ? 'Active' : 'Inactive'}</dd></div></dl></section>
    </div>}
  </main>;
}
