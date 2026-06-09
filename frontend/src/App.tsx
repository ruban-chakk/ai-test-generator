import { Route, Routes, Navigate } from 'react-router-dom';
import RequirementDashboard from './pages/RequirementDashboard';

function App() {
  return (
    <div className="app-shell">
      <Routes>
        <Route path="/" element={<Navigate to="/requirements" replace />} />
        <Route path="/requirements" element={<RequirementDashboard />} />
      </Routes>
    </div>
  );
}

export default App;
