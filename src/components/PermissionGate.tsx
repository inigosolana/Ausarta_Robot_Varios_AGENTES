import React from 'react';
import { useAuth } from '../contexts/AuthContext';
import { useTranslation } from 'react-i18next';
import { BarChart3 } from 'lucide-react';

interface PermissionGateProps {
    view: string;
    children: React.ReactNode;
}

export const PermissionGate: React.FC<PermissionGateProps> = ({ view, children }) => {
    const { hasPermission, isRole } = useAuth();
    const { t } = useTranslation();

    if (view === 'admin' && !isRole('superadmin', 'admin')) {
        return null;
    }

    if (view !== 'admin' && !hasPermission(view)) {
        return (
            <div className="flex items-center justify-center h-full text-gray-400 dark:text-gray-500">
                <div className="text-center">
                    <BarChart3 size={48} className="mx-auto mb-4 opacity-20" />
                    <p className="text-lg font-medium text-gray-600 dark:text-gray-400 mb-1">{t('Restricted Access', 'Acceso Restringido')}</p>
                    <p className="text-sm">{t('No permission to access this module', 'No tienes permisos para acceder a este módulo.')}</p>
                </div>
            </div>
        );
    }

    return <>{children}</>;
};
