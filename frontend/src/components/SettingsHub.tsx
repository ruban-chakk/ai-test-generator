import { Link } from 'react-router-dom';

export type SettingsDestination = {
  key: string;
  title: string;
  description: string;
  to: string;
  icon: 'project' | 'workflow' | 'knowledge' | 'calibration' | 'monitor' | 'import' | 'integration' | 'repository' | 'quality' | 'governance' | 'alert' | 'delivery' | 'mapping' | 'health';
};

const paths: Record<SettingsDestination['icon'], string> = {
  project: 'M4 5h16v14H4z M8 9h8 M8 13h5',
  workflow: 'M5 5h5v5H5z M14 14h5v5h-5z M10 7h4a3 3 0 0 1 3 3v4',
  knowledge: 'M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3z M9 8h6 M9 12h6',
  calibration: 'M4 7h10 M18 7h2 M4 17h2 M10 17h10 M14 4v6 M6 14v6',
  monitor: 'M3 12h4l2-5 4 10 2-5h6',
  import: 'M12 3v12 M7 10l5 5 5-5 M4 20h16',
  integration: 'M8 12h8 M6 8H4a4 4 0 0 0 0 8h2 M18 8h2a4 4 0 0 1 0 8h-2',
  repository: 'M4 6c0-2 16-2 16 0v12c0 2-16 2-16 0z M4 6c0 2 16 2 16 0 M4 12c0 2 16 2 16 0',
  quality: 'M12 3l2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.6l6.2-.9z',
  governance: 'M12 3l8 4v5c0 5-3.4 8-8 9-4.6-1-8-4-8-9V7z M9 12l2 2 4-4',
  alert: 'M12 4a5 5 0 0 1 5 5v4l2 3H5l2-3V9a5 5 0 0 1 5-5z M10 20h4',
  delivery: 'M3 7h12v10H3z M15 10h3l3 3v4h-6 M7 17a2 2 0 1 0 0 .1 M18 17a2 2 0 1 0 0 .1',
  mapping: 'M4 6h6 M14 6h6 M10 6l4 6 M4 18h6 M14 18h6 M10 18l4-6',
  health: 'M4 12h4l2-4 4 8 2-4h4 M12 21C5 17 3 13 3 9a5 5 0 0 1 9-3 5 5 0 0 1 9 3c0 4-2 8-9 12z',
};

export default function SettingsHub({ destinations, label }: { destinations: SettingsDestination[]; label: string }) {
  return <section className="settings-hub" aria-label={label}>{destinations.map((destination) => <Link className="settings-tile" to={destination.to} key={destination.key}><span className="settings-tile-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d={paths[destination.icon]} /></svg></span><span><strong>{destination.title}</strong><small>{destination.description}</small></span><span className="settings-tile-arrow" aria-hidden="true">›</span></Link>)}</section>;
}
