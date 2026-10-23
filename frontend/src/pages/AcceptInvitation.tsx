import { FormEvent, useState } from 'react';
import { acceptInvitation } from '../api';

export default function AcceptInvitation({ token }: { token: string }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [saving, setSaving] = useState(false);
  const [complete, setComplete] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault(); setSaving(true); setError(null);
    try { await acceptInvitation(token, { username, password }); setComplete(true); setPassword(''); }
    catch (err) { setError(err instanceof Error ? err.message : 'Unable to accept invitation'); }
    finally { setSaving(false); }
  }

  return <main className="auth-shell"><section className="auth-card"><span className="brand-mark">AI</span><h1>Accept invitation</h1>{complete ? <><p>Your account has been created with the organization and project access assigned by your administrator.</p><a className="primary-button" href="/">Continue to sign in</a></> : <form onSubmit={submit}><p>Create your account using the email address attached to this invitation.</p><label htmlFor="invite-username">Username</label><input id="invite-username" value={username} onChange={(event) => setUsername(event.target.value)} required /><label htmlFor="invite-password">Password</label><input id="invite-password" type="password" minLength={12} value={password} onChange={(event) => setPassword(event.target.value)} required /><small>Use at least 12 characters.</small>{error ? <div className="error-message" role="alert">{error}</div> : null}<button type="submit" disabled={saving}>{saving ? 'Creating account…' : 'Create account'}</button></form>}</section></main>;
}
