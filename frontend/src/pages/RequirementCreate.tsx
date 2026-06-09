import { FormEvent, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { createRequirement } from '../api';

export default function RequirementCreatePage() {
  const navigate = useNavigate();
  const [externalId, setExternalId] = useState('');
  const [title, setTitle] = useState('');
  const [source, setSource] = useState('manual');
  const [description, setDescription] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSaving(true);

    try {
      const requirement = await createRequirement({
        external_id: externalId || undefined,
        title,
        description,
        source,
      });
      navigate(`/requirements/${requirement.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create requirement');
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="page-container">
      <header className="page-header">
        <div>
          <p className="eyebrow">New requirement</p>
          <h1>Create requirement</h1>
        </div>
        <button className="secondary-button" onClick={() => navigate('/requirements')}>
          Cancel
        </button>
      </header>

      <form className="form-card" onSubmit={handleSubmit}>
        <div className="form-row">
          <label htmlFor="externalId">External ID</label>
          <input
            id="externalId"
            type="text"
            value={externalId}
            onChange={(event) => setExternalId(event.target.value)}
          />
        </div>

        <div className="form-row">
          <label htmlFor="title">Title</label>
          <input
            id="title"
            type="text"
            required
            value={title}
            onChange={(event) => setTitle(event.target.value)}
          />
        </div>

        <div className="form-row">
          <label htmlFor="source">Source</label>
          <select id="source" value={source} onChange={(event) => setSource(event.target.value)}>
            <option value="manual">Manual</option>
            <option value="jira">Jira</option>
            <option value="upload">Upload</option>
          </select>
        </div>

        <div className="form-row">
          <label htmlFor="description">Description</label>
          <textarea
            id="description"
            rows={8}
            required
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </div>

        {error ? <div className="status-message status-error">{error}</div> : null}

        <div className="form-actions">
          <button type="submit" className="primary-button" disabled={saving}>
            {saving ? 'Saving...' : 'Create requirement'}
          </button>
        </div>
      </form>
    </main>
  );
}
