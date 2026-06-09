/**
 * Root application component.
 *
 * Sets up routing and authentication context.
 * Unauthenticated users are redirected to the login page.
 */

import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import Layout from './components/Layout';
import LoginPage from './pages/LoginPage';
import DashboardPage from './pages/DashboardPage';
import MattersPage from './pages/MattersPage';
import CustomFieldsPage from './pages/CustomFieldsPage';
import BulkOperationsPage from './pages/BulkOperationsPage';
import AuditLogPage from './pages/AuditLogPage';

const BillingDashboardPage = lazy(() => import('./pages/BillingDashboardPage'));

function PageLoader() {
  return <div className="flex h-64 items-center justify-center text-slate-400">Loading...</div>;
}

function ProtectedRoute({ children }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="flex h-screen items-center justify-center text-slate-400">Loading...</div>;
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

function AppRoutes() {
  const { user, loading } = useAuth();

  if (loading) {
    return <div className="flex h-screen items-center justify-center text-slate-400">Loading...</div>;
  }

  return (
    <Routes>
      <Route path="/login" element={user ? <Navigate to="/" replace /> : <LoginPage />} />

      <Route element={<ProtectedRoute><Layout /></ProtectedRoute>}>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/billing" element={<Suspense fallback={<PageLoader />}><BillingDashboardPage /></Suspense>} />
        <Route path="/matters" element={<MattersPage />} />
        <Route path="/custom-fields" element={<CustomFieldsPage />} />
        <Route path="/bulk-update" element={<BulkOperationsPage />} />
        <Route path="/audit" element={<AuditLogPage />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  );
}
