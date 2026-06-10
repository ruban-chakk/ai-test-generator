import { Route, Routes, Navigate } from 'react-router-dom';
import RequirementDashboard from './pages/RequirementDashboard';
import RequirementDetail from './pages/RequirementDetail';
import RequirementCreate from './pages/RequirementCreate';
import Operations from './pages/Operations';

function App() {
  return (
    <div className="app-shell">
      <Routes>
        <Route path="/" element={<Navigate to="/requirements" replace />} />
        <Route path="/requirements" element={<RequirementDashboard />} />
        <Route path="/requirements/new" element={<RequirementCreate />} />
        <Route path="/requirements/:id" element={<RequirementDetail />} />
        <Route path="/operations" element={<Operations />} />
      </Routes>
    </div>
  );
}

export default App;
