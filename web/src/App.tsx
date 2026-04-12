import { Routes, Route, Navigate, useLocation } from "react-router-dom";
import { Layout } from "./components/Layout";
import { RouteErrorBoundary } from "./components/RouteErrorBoundary";
import { Dashboard } from "./pages/Dashboard";
import { Tasks } from "./pages/Tasks";
import { Benchmarks } from "./pages/Benchmarks";
import { Logs } from "./pages/Logs";
import { Settings } from "./pages/Settings";
import { Setup } from "./pages/Setup";
import { IterationDetailPage } from "./pages/IterationDetailPage";

export function App() {
  const location = useLocation();
  return (
    <Layout>
      <RouteErrorBoundary key={location.pathname}>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/setup" element={<Setup />} />
          <Route path="/tasks" element={<Tasks />} />
          <Route path="/benchmarks" element={<Benchmarks />} />
          <Route path="/logs/iteration/:iterationNum" element={<IterationDetailPage />} />
          <Route path="/logs" element={<Logs />} />
          <Route path="/iterations" element={<Navigate to="/logs" replace />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </RouteErrorBoundary>
    </Layout>
  );
}
