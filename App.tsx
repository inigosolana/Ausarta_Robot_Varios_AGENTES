
import React, { useState, useEffect } from 'react';
import {
  LayoutDashboard,
  Bot,
  Building2,
  Megaphone,
  Zap,
  Cpu,
  PhoneCall,
  BarChart3,
  ClipboardList,
  PanelLeftClose,
  PanelLeftOpen,
  Users,
  LogOut,
  Phone,
  Loader2,
  Moon,
  Sun,
  BotMessageSquare
} from 'lucide-react';
import { ViewState } from './types';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Toaster, toast } from 'react-hot-toast';
import { useAuth } from './contexts/AuthContext';
import { supabase } from './lib/supabase';
import { PermissionGate } from './components/PermissionGate';
import SidebarItem from './components/SidebarItem';
import TelephonyView from './views/TelephonyView';
import ModelsView from './views/ModelsView';
import { CampaignsView } from './views/CampaignsView';
import AgentListView from './views/AgentListView';
import TestCallView from './views/TestCallView';
import LiveCallView from './views/LiveCallView';
import DashboardView from './views/DashboardView';
import ResultsView from './views/ResultsView';
import UsageView from './views/UsageView';
import UserManagementView from './views/UserManagementView';
import AgentManagementView from './views/AgentManagementView';
import LoginView from './views/LoginView';
import CrmIntegrationView from './views/CrmIntegrationView';
import AssistantView from './views/AssistantView';

const App: React.FC = () => {
  const { user, profile, loading, signOut, hasPermission, isRole } = useAuth();
  const { t, i18n } = useTranslation();
  const isAusartaAdmin = profile?.empresas?.nombre === 'Ausarta' && isRole('admin');
  const isPlatformOwner = isRole('superadmin') || isAusartaAdmin;
  const [currentView, setCurrentView] = useState<ViewState | 'results' | 'admin' | 'crm'>('overview');
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [isCalling, setIsCalling] = useState(false);
  const [isDarkMode, setIsDarkMode] = useState(false);
  const queryClient = useQueryClient();
  const API_URL = import.meta.env.VITE_API_URL || window.location.origin;

  useEffect(() => {
    setIsDarkMode(document.documentElement.classList.contains('dark'));
  }, []);

  const toggleDarkMode = () => {
    const nextDark = document.documentElement.classList.toggle('dark');
    setIsDarkMode(nextDark);
    localStorage.theme = nextDark ? 'dark' : 'light';
  };

  const { data: alerts = [] } = useQuery({
    queryKey: ['alerts'],
    queryFn: async () => {
      const res = await fetch(`${API_URL}/api/alerts`);
      if (!res.ok) throw new Error('Failed to fetch alerts');
      return res.json();
    }
  });

  useEffect(() => {
    const channel = supabase.channel('realtime_alerts')
      .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'alertas' }, payload => {
        toast.error(`Nueva alerta: ${payload.new.message}`, { icon: '⚠️' });
        queryClient.invalidateQueries({ queryKey: ['alerts'] });
      })
      .on('postgres_changes', { event: 'UPDATE', schema: 'public', table: 'alertas' }, payload => {
        queryClient.invalidateQueries({ queryKey: ['alerts'] });
      })
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [queryClient]);

  // Show loading spinner
  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen bg-gray-50">
        <div className="text-center">
          <Loader2 className="animate-spin mx-auto text-blue-500 mb-4" size={40} />
          <p className="text-gray-500 text-sm">{t('Loading...', 'Cargando...')}</p>
        </div>
      </div>
    );
  }

  // Show login if not authenticated or if in password recovery/invitation flow
  const isAuthFlow = (window.location.hash + window.location.search).includes('type=recovery') ||
    (window.location.hash + window.location.search).includes('type=signup') ||
    (window.location.hash + window.location.search).includes('type=invite');

  if ((!user || !profile) || isAuthFlow) {
    return <LoginView />;
  }

  const renderContent = () => {
    switch (currentView) {
      case 'telephony':
        return <PermissionGate view="telephony"><TelephonyView /></PermissionGate>;
      case 'campaigns':
        return <PermissionGate view="campaigns"><CampaignsView /></PermissionGate>;
      case 'create-agents':
      case 'empresas':
        return <PermissionGate view="empresas"><AgentListView /></PermissionGate>;
      case 'agents':
        return <PermissionGate view="agents"><AgentManagementView /></PermissionGate>;
      case 'test-call':
        return <PermissionGate view="test-call"><TestCallView /></PermissionGate>;
      case 'overview':
        return <PermissionGate view="overview"><DashboardView /></PermissionGate>;
      case 'results':
        return <PermissionGate view="results"><ResultsView /></PermissionGate>;
      case 'usage':
        return <PermissionGate view="usage"><UsageView /></PermissionGate>;
      case 'models':
        return <PermissionGate view="models"><ModelsView /></PermissionGate>;
      case 'admin':
        return <PermissionGate view="admin"><UserManagementView /></PermissionGate>;
      case 'crm':
        return <CrmIntegrationView />;
      case 'assistant':
        return <PermissionGate view="assistant"><AssistantView /></PermissionGate>;
      case 'automation':
      case 'tools':
      default:
        return (
          <div className="flex items-center justify-center h-full text-gray-400">
            <div className="text-center">
              <BarChart3 size={48} className="mx-auto mb-4 opacity-20" />
              <p>{t('Module in development', 'Módulo en desarrollo')} - {currentView}</p>
            </div>
          </div>
        );
    }
  };

  const resolveAlert = async (id: number) => {
    try {
      await fetch(`${API_URL}/api/alerts/${id}/resolve`, { method: 'POST' });
      queryClient.invalidateQueries({ queryKey: ['alerts'] });
    } catch (e) { }
  };

  const getRoleLabel = () => {
    switch (profile.role) {
      case 'superadmin': return 'Superadmin';
      case 'admin': return 'Admin';
      default: return 'Usuario';
    }
  };

  return (
    <>
      <Toaster position="bottom-right" toastOptions={{ className: 'dark:bg-gray-800 dark:text-white border dark:border-gray-700' }} />
      <div className="flex h-screen w-full bg-[#fcfcfc] dark:bg-gray-900 overflow-hidden text-gray-900 dark:text-gray-100 transition-colors duration-200">
        {/* Sidebar */}
        <aside className={`${isSidebarOpen ? 'w-64' : 'w-20'} border-r border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-800 flex flex-col transition-all duration-300 ease-in-out`}>
          <div className="p-4 flex items-center justify-between border-b border-gray-50 dark:border-gray-700">
            <div className={`flex items-center gap-3 font-bold text-gray-800 dark:text-gray-100 overflow-hidden ${!isSidebarOpen && 'hidden'}`}>
              <img src="/ausarta.png" alt="Ausarta Logo" className="h-8 w-auto object-contain dark:invert" />
              <div className="flex flex-col">
                <span className="text-lg leading-none tracking-tight">Ausarta</span>
                <span className="text-[10px] text-gray-400 font-normal">Voice AI v2.0</span>
              </div>
            </div>
            <button onClick={() => setIsSidebarOpen(!isSidebarOpen)} className="p-1 hover:bg-gray-50 dark:hover:bg-gray-700 rounded text-gray-400 dark:text-gray-500">
              {isSidebarOpen ? <PanelLeftClose size={18} /> : <PanelLeftOpen size={18} />}
            </button>
          </div>

          <nav className="flex-1 overflow-y-auto px-3 py-2 space-y-1">
            {hasPermission('overview') && (
              <SidebarItem
                icon={<LayoutDashboard size={18} />}
                label={t('Dashboard')}
                isActive={currentView === 'overview'}
                onClick={() => setCurrentView('overview')}
                collapsed={!isSidebarOpen}
              />
            )}

            <div className={`mt-6 mb-2 px-3 text-[10px] uppercase tracking-wider font-bold text-gray-400 ${!isSidebarOpen && 'hidden'}`}>
              Build
            </div>
            {isPlatformOwner && hasPermission('empresas') && (
              <SidebarItem
                icon={<Building2 size={18} />}
                label={t('Empresas')}
                isActive={currentView === 'empresas' || currentView === 'create-agents'}
                onClick={() => setCurrentView('empresas')}
                collapsed={!isSidebarOpen}
              />
            )}
            {hasPermission('agents') && (
              <SidebarItem
                icon={<Bot size={18} />}
                label={t('Agents')}
                isActive={currentView === 'agents'}
                onClick={() => setCurrentView('agents')}
                collapsed={!isSidebarOpen}
              />
            )}
            {hasPermission('test-call') && (
              <SidebarItem
                icon={<Phone size={18} />}
                label={t('Test Call')}
                isActive={currentView === 'test-call'}
                onClick={() => setCurrentView('test-call')}
                collapsed={!isSidebarOpen}
              />
            )}
            {hasPermission('campaigns') && (
              <SidebarItem
                icon={<Megaphone size={18} />}
                label={t('Campaigns')}
                isActive={currentView === 'campaigns'}
                onClick={() => setCurrentView('campaigns')}
                collapsed={!isSidebarOpen}
              />
            )}
            {isPlatformOwner && hasPermission('models') && (
              <SidebarItem
                icon={<Cpu size={18} />}
                label="AI Models"
                isActive={currentView === 'models'}
                onClick={() => setCurrentView('models')}
                collapsed={!isSidebarOpen}
              />
            )}
            {isPlatformOwner && hasPermission('telephony') && (
              <SidebarItem
                icon={<PhoneCall size={18} />}
                label="Telephony"
                isActive={currentView === 'telephony'}
                onClick={() => setCurrentView('telephony')}
                collapsed={!isSidebarOpen}
              />
            )}

            <div className={`mt-6 mb-2 px-3 text-[10px] uppercase tracking-wider font-bold text-gray-400 ${!isSidebarOpen && 'hidden'}`}>
              Observe
            </div>
            {hasPermission('results') && (
              <SidebarItem
                icon={<ClipboardList size={18} />}
                label={t('Results')}
                isActive={currentView === 'results'}
                onClick={() => setCurrentView('results')}
                collapsed={!isSidebarOpen}
              />
            )}
            {hasPermission('assistant') && (
              <SidebarItem
                icon={<BotMessageSquare size={18} />}
                label="Ausarta Copilot"
                isActive={currentView === 'assistant'}
                onClick={() => setCurrentView('assistant')}
                collapsed={!isSidebarOpen}
              />
            )}
            {hasPermission('usage') && (
              <SidebarItem
                icon={<BarChart3 size={18} />}
                label="Usage"
                isActive={currentView === 'usage'}
                onClick={() => setCurrentView('usage')}
                collapsed={!isSidebarOpen}
              />
            )}

            {/* Admin section - only for admin and superadmin */}
            {isRole('superadmin', 'admin') && (
              <>
                <div className={`mt-6 mb-2 px-3 text-[10px] uppercase tracking-wider font-bold text-gray-400 ${!isSidebarOpen && 'hidden'}`}>
                  Admin
                </div>
                <SidebarItem
                  icon={<Users size={18} />}
                  label="Usuarios"
                  isActive={currentView === 'admin'}
                  onClick={() => setCurrentView('admin')}
                  collapsed={!isSidebarOpen}
                />
                <SidebarItem
                  icon={<Building2 size={18} />}
                  label="Integraciones CRM"
                  isActive={currentView === 'crm'}
                  onClick={() => setCurrentView('crm')}
                  collapsed={!isSidebarOpen}
                />
              </>
            )}
          </nav>

          {/* User info + Logout */}
          <div className="p-4 border-t border-gray-50 dark:border-gray-700 space-y-2">
            <div className={`flex items-center gap-2 text-sm ${!isSidebarOpen && 'justify-center'}`}>
              <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-400 to-blue-600 flex items-center justify-center text-white text-xs font-bold flex-shrink-0">
                {(profile.full_name || profile.email).charAt(0).toUpperCase()}
              </div>
              {isSidebarOpen && (
                <div className="overflow-hidden">
                  <p className="font-medium text-gray-800 dark:text-gray-200 truncate text-xs">{profile.full_name || profile.email}</p>
                  <p className="text-[10px] text-gray-400 dark:text-gray-500">{getRoleLabel()}</p>
                </div>
              )}
            </div>
            <div className="flex justify-between items-center gap-2">
              <button
                onClick={signOut}
                className={`flex-1 flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400 hover:text-red-600 dark:hover:text-red-400 px-2 py-1 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-colors ${!isSidebarOpen && 'justify-center'}`}
              >
                <LogOut size={16} />
                {isSidebarOpen && t("Logout")}
              </button>
              <button
                onClick={toggleDarkMode}
                className="p-1.5 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors"
              >
                {isDarkMode ? <Sun size={16} /> : <Moon size={16} />}
              </button>
            </div>

            {isSidebarOpen && (
              <div className="flex justify-center gap-2 mt-4 pt-2 border-t border-gray-50 dark:border-gray-700">
                <button onClick={() => i18n.changeLanguage('es')} className={`text-xs px-2 py-1 rounded transition-colors ${i18n.language.startsWith('es') ? 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 font-bold' : 'text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700'}`}>ES</button>
                <button onClick={() => i18n.changeLanguage('en')} className={`text-xs px-2 py-1 rounded transition-colors ${i18n.language.startsWith('en') ? 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 font-bold' : 'text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700'}`}>EN</button>
                <button onClick={() => i18n.changeLanguage('eu')} className={`text-xs px-2 py-1 rounded transition-colors ${i18n.language.startsWith('eu') ? 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 font-bold' : 'text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700'}`}>EU</button>
                <button onClick={() => i18n.changeLanguage('gl')} className={`text-xs px-2 py-1 rounded transition-colors ${i18n.language.startsWith('gl') ? 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 font-bold' : 'text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700'}`}>GL</button>
              </div>
            )}
          </div>
        </aside>

        {/* Main Content */}
        <main className="flex-1 overflow-y-auto p-8 relative">
          <div className="max-w-6xl mx-auto">
            {alerts.length > 0 && (
              <div className="mb-6 space-y-2">
                {alerts.map((alert: any) => (
                  <div key={alert.id} className="bg-red-50 border border-red-200 text-red-700 p-4 rounded-lg flex items-center justify-between shadow-sm animate-pulse">
                    <div className="flex items-center gap-3">
                      <div className="bg-red-100 p-2 rounded-full">
                        <Zap className="w-5 h-5 text-red-600" />
                      </div>
                      <div>
                        <h3 className="font-bold text-sm uppercase">{alert.type === 'api_limit' ? '⚠️ API Limit Reached' : 'System Alert'}</h3>
                        <p className="text-sm">{alert.message}</p>
                      </div>
                    </div>
                    <button
                      onClick={() => resolveAlert(alert.id)}
                      className="px-3 py-1 bg-red-100 rounded text-xs hover:bg-red-200"
                    >
                      Dismiss
                    </button>
                  </div>
                ))}
              </div>
            )}
            {renderContent()}
          </div>
        </main>

        {/* Live Call Overlay */}
        {isCalling && (
          <LiveCallView onClose={() => setIsCalling(false)} />
        )}
      </div>
    </>
  );
};

export default App;
