import type { RequirementSummary } from '../pages/RequirementDashboard';

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
        <span>Updated {new Date(requirement.updated_at).toLocaleDateString()}</span>
        <button className="secondary-button">Open</button>
      </div>
    </article>
  );
}
