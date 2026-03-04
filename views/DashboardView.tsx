import React from 'react';
import { useAuth } from '../contexts/AuthContext';
import AdminDashboard from '../components/AdminDashboard';
import ClientDashboard from '../components/ClientDashboard';

interface Props {
    empresaId?: number;
    agentId?: number;
    campaignId?: number;
    title?: string;
    hideIntegrations?: boolean;
}

/**
 * DashboardView acts as a router/semaphore to choose between
 * the Admin view (system health) and the Client view (ROI/Business).
 */
const DashboardView: React.FC<Props> = (props) => {
    const { isPlatformOwner, profile } = useAuth();

    // If superadmin or Ausarta admin, show the full admin dashboard
    if (isPlatformOwner) {
        return <AdminDashboard {...props} />;
    }

    // For regular clients, we show the ROI-focused dashboard
    // We pass the company ID from the profile if not explicitly provided as a prop
    return <ClientDashboard empresaId={props.empresaId || profile?.empresa_id} />;
};

export default DashboardView;
