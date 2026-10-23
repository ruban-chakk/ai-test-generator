import { Link } from 'react-router-dom';

export default function BackLink({ to, label }: { to: string; label: string }) {
  return (
    <Link className="back-link" to={to} aria-label={label}>
      <span aria-hidden="true">←</span>
      {label}
    </Link>
  );
}
