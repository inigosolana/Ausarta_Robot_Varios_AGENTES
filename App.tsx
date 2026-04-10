import React, { lazy } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { PermissionGate } from './components/PermissionGate';
import ProtectedRoute from './components/ProtectedRoute';
import AppShell from './components/AppShell';

const CampaignsView      = lazy(() => import('./views/CampaignsView').then(m => ({ default: m.CampaignsView })));
const AgentListView      = lazy(() => import('./views/AgentListView'));
const TestCallView       = lazy(() => import('./views/TestCallView'));
const DashboardView      = lazy(() => import('./views/DashboardView'));
const ResultsView        = lazy(() => import('./views/ResultsView'));
const UsageView          = lazy(() => import('./views/UsageView'));
const UserManagementView = lazy(() => import('./views/UserManagementView'));
const AgentManagementView = lazy(() => import('./views/AgentManagementView'));
const LoginView          = lazy(() => import('./views/LoginView'));
const CrmIntegrationView = lazy(() => import('./views/CrmIntegrationView'));
const AssistantView      = lazy(() => import('./views/AssistantView'));
const ProfileView        = lazy(() => import('./views/ProfileView'));

const App: React.FC = () => (
  <Routes>
    {/* Public */}
    <Route path="/login" element={<LoginView />} />

    {/* Protected — ProtectedRoute guards auth, AppShell provides the layout */}
    <Route element={<ProtectedRoute />}>
      <Route element={<AppShell />}>
        <Route index element={<PermissionGate view="overview"><DashboardView /></PermissionGate>} />
        <Route path="campaigns" element={<PermissionGate view="campaigns"><CampaignsView /></PermissionGate>} />
        <Route path="empresas"  element={<PermissionGate view="empresas"><AgentListView /></PermissionGate>} />
        <Route path="agents"    element={<PermissionGate view="agents"><AgentManagementView /></PermissionGate>} />
        <Route path="test-call" element={<PermissionGate view="test-call"><TestCallView /></PermissionGate>} />
        <Route path="results"   element={<PermissionGate view="results"><ResultsView /></PermissionGate>} />
        <Route path="copilot"   element={<PermissionGate view="assistant"><AssistantView /></PermissionGate>} />
        <Route path="usage"     element={<PermissionGate view="usage"><UsageView /></PermissionGate>} />
        <Route path="admin"     element={<PermissionGate view="admin"><UserManagementView /></PermissionGate>} />
        <Route path="crm"       element={<CrmIntegrationView />} />
        <Route path="profile"   element={<ProfileView />} />
      </Route>
    </Route>

    {/* Fallback */}
    <Route path="*" element={<Navigate to="/" replace />} />
  </Routes>
);

export default App;
