import { Link } from 'react-router-dom';
import type { RequirementSummary } from '../api';

interface Props {
  requirement: RequirementSummary;
}

export default function RequirementCard({ requirement }: Props) {
  return (
    <article className="card">
      <div className="card-header">
        <div>
          <p className="chip">{requirement.source}</p>
          <h2>{requirement.title}</h2>
        </div>
        <span className="status-pill">{requirement.status}</span>
      </div>
      <p className="meta">{requirement.external_id}</p>
      <div className="card-footer">
        <span>Updated {requirement.updated_at ? new Date(requirement.updated_at).toLocaleDateString() : '—'}</span>
        <Link to={`/requirements/${requirement.id}`} className="secondary-button">
          Open
        </Link>
      </div>
    </article>
  );
}
