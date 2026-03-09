
import React, { useState, useEffect, Suspense, lazy } from 'react';
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
  BotMessageSquare,
  Settings,
  Share2
} from 'lucide-react';
import { ViewState } from './types';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Toaster, toast } from 'react-hot-toast';
import { useAuth } from './contexts/AuthContext';
import { supabase } from './lib/supabase';
import { PermissionGate } from './components/PermissionGate';
import SidebarItem from './components/SidebarItem';
import AssistantPanel from './components/AssistantPanel';

// Lazy loading views for better performance
const CampaignsView = lazy(() => import('./views/CampaignsView').then(m => ({ default: m.CampaignsView })));
const AgentListView = lazy(() => import('./views/AgentListView'));
const TestCallView = lazy(() => import('./views/TestCallView'));
const LiveCallView = lazy(() => import('./views/LiveCallView'));
const DashboardView = lazy(() => import('./views/DashboardView'));
const ResultsView = lazy(() => import('./views/ResultsView'));
const UsageView = lazy(() => import('./views/UsageView'));
const UserManagementView = lazy(() => import('./views/UserManagementView'));
const AgentManagementView = lazy(() => import('./views/AgentManagementView'));
const LoginView = lazy(() => import('./views/LoginView'));
const CrmIntegrationView = lazy(() => import('./views/CrmIntegrationView'));
const AssistantView = lazy(() => import('./views/AssistantView'));
const ProfileView = lazy(() => import('./views/ProfileView'));

const ViewLoader = () => (
  <div className="flex flex-col items-center justify-center h-full min-h-[400px]">
    <Loader2 className="animate-spin text-blue-500 mb-4" size={32} />
    <p className="text-gray-400 text-sm animate-pulse italic">Cargando vista...</p>
  </div>
);


const App: React.FC = () => {
  const { user, profile, realProfile, loading, signOut, hasPermission, isRole, refreshProfile, isPlatformOwner, setSpoofedRole, setSpoofedEmpresa } = useAuth();
  const { t, i18n } = useTranslation();
  const [currentView, setCurrentView] = useState<ViewState | 'results' | 'admin' | 'crm' | 'profile'>('overview');
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [isChatOpen, setIsChatOpen] = useState(false);
  const [isCalling, setIsCalling] = useState(false);
  const [isDarkMode, setIsDarkMode] = useState(false);
  const queryClient = useQueryClient();
  const API_URL = import.meta.env.VITE_API_URL || window.location.origin;

  const isRootUser = realProfile?.email === 'admin@ausarta.net' ||
    realProfile?.email === 'inigo2.solana@ausarta.net' ||
    realProfile?.email === 'inigosolana@gmail.com';
  const isAusartaAdmin = realProfile?.empresas?.nombre === 'Ausarta' && realProfile?.role === 'admin';
  const canSimulation = (realProfile?.role === 'superadmin' || isRootUser || isAusartaAdmin) && (realProfile?.empresas?.nombre === 'Ausarta' || isRootUser);

  // Auto-redirect if role change makes current view inaccessible
  useEffect(() => {
    if (currentView === 'profile') return;
    if (currentView === 'overview') return;

    // Check if the current view is still accessible
    if (!hasPermission(currentView)) {
      setCurrentView('overview');
    }
  }, [profile?.role, currentView, profile?.empresa_id]);

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

  const { data: companies = [] } = useQuery({
    queryKey: ['companies'],
    queryFn: async () => {
      const res = await fetch(`${API_URL}/api/empresas`);
      if (!res.ok) throw new Error('Failed to fetch companies');
      return res.json();
    },
    enabled: canSimulation
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
    return (
      <Suspense fallback={<ViewLoader />}>
        {(() => {
          switch (currentView) {

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

            case 'admin':
              return <PermissionGate view="admin"><UserManagementView /></PermissionGate>;
            case 'crm':
              return <CrmIntegrationView />;
            case 'assistant':
              return <PermissionGate view="assistant"><AssistantView /></PermissionGate>;
            case 'profile':
              return <ProfileView />;
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
        })()}
      </Suspense>
    );
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
      default: return t('User', 'Usuario');
    }
  };

  return (
    <>
      <Toaster position="bottom-right" toastOptions={{ className: 'dark:bg-gray-800 dark:text-white border dark:border-gray-700' }} />
      <div className="flex min-h-screen w-full bg-[#fcfcfc] dark:bg-gray-900 overflow-hidden text-gray-900 dark:text-gray-100 transition-colors duration-200 flex-col md:flex-row">
        {/* Sidebar */}
        <aside className={`${isSidebarOpen ? 'md:w-64' : 'md:w-20'} w-full border-b md:border-b-0 md:border-r border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-800 flex flex-col transition-all duration-300 ease-in-out`}>
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
              {t('Build', 'Construcción')}
            </div>
            {isPlatformOwner && hasPermission('empresas') && (
              <SidebarItem
                icon={<Building2 size={18} />}
                label={t('Companies', 'Empresas')}
                isActive={currentView === 'empresas'}
                onClick={() => setCurrentView('empresas')}
                collapsed={!isSidebarOpen}
              />
            )}

            {hasPermission('agents') && (
              <SidebarItem
                icon={<Bot size={18} />}
                label={t('Agentes', 'Agentes')}
                isActive={currentView === 'agents'}
                onClick={() => setCurrentView('agents')}
                collapsed={!isSidebarOpen}
              />
            )}

            {hasPermission('test-call') && (
              <SidebarItem
                icon={<Phone size={18} />}
                label={t('Test Call', 'Llamada Prueba')}
                isActive={currentView === 'test-call'}
                onClick={() => setCurrentView('test-call')}
                collapsed={!isSidebarOpen}
              />
            )}

            {hasPermission('campaigns') && (
              <SidebarItem
                icon={<Megaphone size={18} />}
                label={t('Campaigns', 'Campañas')}
                isActive={currentView === 'campaigns'}
                onClick={() => setCurrentView('campaigns')}
                collapsed={!isSidebarOpen}
              />
            )}

            <div className={`mt-6 mb-2 px-3 text-[10px] uppercase tracking-wider font-bold text-gray-400 ${!isSidebarOpen && 'hidden'}`}>
              {t('Analysis', 'Análisis')}
            </div>
            {hasPermission('results') && (
              <SidebarItem
                icon={<BarChart3 size={18} />}
                label={t('Results', 'Resultados')}
                isActive={currentView === 'results'}
                onClick={() => setCurrentView('results')}
                collapsed={!isSidebarOpen}
              />
            )}

            {hasPermission('assistant') && (
              <SidebarItem
                icon={<BotMessageSquare size={18} />}
                label={t('Ausarta Copilot', 'Ausarta Copilot')}
                isActive={currentView === 'assistant'}
                onClick={() => setCurrentView('assistant')}
                collapsed={!isSidebarOpen}
              />
            )}

            {hasPermission('usage') && (
              <SidebarItem
                icon={<Zap size={18} />}
                label={t('Usage', 'Uso')}
                isActive={currentView === 'usage'}
                onClick={() => setCurrentView('usage')}
                collapsed={!isSidebarOpen}
              />
            )}

            {hasPermission('admin') && (
              <SidebarItem
                icon={<Settings size={18} />}
                label={t('Admin', 'Administración')}
                isActive={currentView === 'admin'}
                onClick={() => setCurrentView('admin')}
                collapsed={!isSidebarOpen}
              />
            )}

            {hasPermission('crm') && (
              <SidebarItem
                icon={<Share2 size={18} />}
                label={t('CRM Integration', 'Integración CRM')}
                isActive={currentView === 'crm'}
                onClick={() => setCurrentView('crm')}
                collapsed={!isSidebarOpen}
              />
            )}
          </nav>

          {/* User info + Logout */}
          <div className="p-4 border-t border-gray-50 dark:border-gray-700 space-y-2">
            <div
              onClick={() => setCurrentView('profile')}
              className={`flex items-center gap-2 text-sm cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700 p-2 rounded-xl transition-all ${!isSidebarOpen && 'justify-center'}`}
            >
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

            {/* If superadmin or original, show context switcher panel */}
            {canSimulation && isSidebarOpen && (
              <div className="mx-2 mb-4 p-3 bg-indigo-50 dark:bg-indigo-900/10 border border-indigo-100 dark:border-indigo-800/50 rounded-xl space-y-3">
                <div className="flex items-center justify-between">
                  <p className="text-[9px] text-indigo-600 dark:text-indigo-400 font-bold uppercase tracking-wider">{t('Context Simulation')}</p>
                  {profile.role !== 'superadmin' && <div className="w-2 h-2 rounded-full bg-red-500 animate-pulse"></div>}
                </div>

                {/* Role Switcher */}
                <div className="flex gap-1">
                  {(['superadmin', 'admin', 'user'] as const)
                    .filter(r => realProfile?.role === 'superadmin' || isRootUser || r !== 'superadmin')
                    .map((r) => (
                      <button
                        key={r}
                        title={r}
                        onClick={() => {
                          setSpoofedRole(r === realProfile?.role ? null : r);
                          toast.success(`${t('Simulating')} ${r}`);
                        }}
                        className={`text-[9px] flex-1 py-1 rounded transition-all font-bold ${profile?.role === r
                          ? 'bg-indigo-600 text-white shadow-sm'
                          : 'bg-white dark:bg-gray-800 text-gray-500 hover:bg-indigo-50'
                          }`}
                      >
                        {r.charAt(0).toUpperCase()}
                      </button>
                    ))}
                </div>

                {/* Company Switcher */}
                <select
                  value={profile?.empresa_id || ''}
                  onChange={(e) => {
                    const val = e.target.value === '' ? null : Number(e.target.value);
                    const isReturningToSelf = val === realProfile?.empresa_id || val === null;

                    setSpoofedEmpresa(val === realProfile?.empresa_id ? null : val);

                    // Smart Role Switching:
                    // If moving to another company, default to 'user' role
                    // If returning to own company (Ausarta), restore original role
                    if (!isReturningToSelf && realProfile?.role === 'admin') {
                      setSpoofedRole('user');
                    } else if (isReturningToSelf) {
                      setSpoofedRole(null);
                    }

                    toast.success(t('Viewing company context'));
                  }}
                  className="w-full text-[10px] py-1 px-1 border border-indigo-100 dark:border-indigo-800 dark:bg-gray-800 rounded outline-none focus:ring-1 focus:ring-indigo-500 font-medium"
                >
                  <option value="">-- {t('No Company')} --</option>
                  {companies.map((c: any) => (
                    <option key={c.id} value={c.id}>{c.nombre}</option>
                  ))}
                </select>

                {(profile?.role !== realProfile?.role || profile?.empresa_id !== realProfile?.empresa_id) && (
                  <button
                    onClick={() => {
                      setSpoofedRole(null);
                      setSpoofedEmpresa(null);
                      toast.success(t('Context restored'));
                    }}
                    className="text-[9px] font-bold text-white bg-red-600 py-1 rounded hover:bg-red-700 w-full transition-all"
                  >
                    {t('Restore Reality')}
                  </button>
                )}
              </div>
            )}

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
        <main className={`flex-1 overflow-y-auto p-4 md:p-8 relative transition-all duration-300 ${isChatOpen ? 'mr-0 sm:mr-[400px]' : 'mr-0'}`}>
          <div className="w-full max-w-6xl mx-auto">
            {alerts.length > 0 && (
              <div className="mb-6 space-y-2">
                {alerts.map((alert: any) => (
                  <div key={alert.id} className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-400 p-4 rounded-xl flex items-center justify-between shadow-sm animate-pulse">
                    <div className="flex items-center gap-3">
                      <div className="bg-red-100 dark:bg-red-800/40 p-2 rounded-full">
                        <Zap className="w-5 h-5 text-red-600 dark:text-red-400" />
                      </div>
                      <div>
                        <p className="font-bold text-sm">{alert.type === 'error' ? t('Critical System Error', 'Error Crítico del Sistema') : t('System Alert', 'Alerta del Sistema')}</p>
                        <p className="text-xs opacity-80">{alert.message}</p>
                      </div>
                    </div>
                    <button onClick={() => resolveAlert(alert.id)} className="text-xs font-bold hover:underline">{t('Resolve', 'Resolver')}</button>
                  </div>
                ))}
              </div>
            )}
            {renderContent()}
          </div>

          {/* Floating Bot Button */}
          {!isChatOpen && (
            <button
              onClick={() => setIsChatOpen(true)}
              className="fixed bottom-8 right-8 w-16 h-16 bg-blue-600 text-white rounded-full flex items-center justify-center shadow-2xl hover:bg-blue-700 transition-all hover:scale-110 active:scale-95 z-40 group overflow-hidden"
            >
              <div className="absolute inset-0 bg-blue-500 rounded-full animate-ping opacity-20 pointer-events-none group-hover:block"></div>
              <Bot size={28} />
            </button>
          )}
        </main>

        <AssistantPanel isOpen={isChatOpen} onClose={() => setIsChatOpen(false)} />

        {/* Live Call Overlay */}
        {isCalling && (
          <LiveCallView onClose={() => setIsCalling(false)} />
        )}
      </div >
    </>
  );
};

export default App;
