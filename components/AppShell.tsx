import React, { useState, useEffect, Suspense, lazy } from 'react';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import {
  LayoutDashboard,
  Bot,
  Building2,
  Megaphone,
  Zap,
  BarChart3,
  PanelLeftClose,
  PanelLeftOpen,
  LogOut,
  Phone,
  Loader2,
  Moon,
  Sun,
  BotMessageSquare,
  Settings,
  Share2,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Toaster, toast } from 'react-hot-toast';
import { useAuth } from '../contexts/AuthContext';
import { supabase } from '../lib/supabase';
import SidebarItem from './SidebarItem';
import AssistantPanel from './AssistantPanel';

const LiveCallView = lazy(() => import('../views/LiveCallView'));

const ViewLoader = () => (
  <div className="flex flex-col items-center justify-center h-full min-h-[400px]">
    <Loader2 className="animate-spin text-blue-500 mb-4" size={32} />
    <p className="text-gray-400 text-sm animate-pulse italic">Cargando vista...</p>
  </div>
);

const AppShell: React.FC = () => {
  const {
    profile, realProfile, signOut, hasPermission,
    isPlatformOwner, setSpoofedRole, setSpoofedEmpresa,
  } = useAuth();
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [isChatOpen, setIsChatOpen] = useState(false);
  const [isCalling, setIsCalling] = useState(false);
  const [isDarkMode, setIsDarkMode] = useState(false);
  const [hiddenAlerts, setHiddenAlerts] = useState<Set<number>>(new Set());
  const queryClient = useQueryClient();
  const API_URL = import.meta.env.VITE_API_URL || window.location.origin;

  const isRootUser =
    realProfile?.email === 'admin@ausarta.net' ||
    realProfile?.email === 'inigo2.solana@ausarta.net' ||
    realProfile?.email === 'inigosolana@gmail.com';
  const isAusartaAdmin =
    realProfile?.empresas?.nombre?.toLowerCase() === 'ausarta' && realProfile?.role === 'admin';
  const canSimulation = realProfile?.role === 'superadmin' || isRootUser || isAusartaAdmin;

  // Redirect to "/" if role change makes current path inaccessible
  useEffect(() => {
    const pathToPermission: Record<string, string> = {
      '/campaigns': 'campaigns',
      '/empresas': 'empresas',
      '/agents': 'agents',
      '/test-call': 'test-call',
      '/results': 'results',
      '/usage': 'usage',
      '/admin': 'admin',
      '/crm': 'crm',
      '/copilot': 'assistant',
    };
    const perm = pathToPermission[location.pathname];
    if (perm && !hasPermission(perm)) {
      navigate('/', { replace: true });
    }
  }, [profile?.role, location.pathname, profile?.empresa_id]);

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
    },
  });

  const { data: companies = [] } = useQuery({
    queryKey: ['companies'],
    queryFn: async () => {
      const res = await fetch(`${API_URL}/api/empresas`);
      if (!res.ok) throw new Error('Failed to fetch companies');
      return res.json();
    },
    enabled: canSimulation,
  });

  // Auto-hide alert banners after 8 seconds
  useEffect(() => {
    if (!alerts.length) return;
    const timers = alerts
      .filter((a: any) => !hiddenAlerts.has(a.id))
      .map((a: any) =>
        setTimeout(() => setHiddenAlerts(prev => new Set([...prev, a.id])), 8000)
      );
    return () => timers.forEach(clearTimeout);
  }, [alerts]);

  useEffect(() => {
    const channel = supabase
      .channel('realtime_alerts')
      .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'alertas' }, payload => {
        toast.error(`Nueva alerta: ${payload.new.message}`, { icon: '⚠️' });
        queryClient.invalidateQueries({ queryKey: ['alerts'] });
      })
      .on('postgres_changes', { event: 'UPDATE', schema: 'public', table: 'alertas' }, () => {
        queryClient.invalidateQueries({ queryKey: ['alerts'] });
      })
      .subscribe();
    return () => { supabase.removeChannel(channel); };
  }, [queryClient]);

  const resolveAlert = async (id: number) => {
    try {
      await fetch(`${API_URL}/api/alerts/${id}/resolve`, { method: 'POST' });
      queryClient.invalidateQueries({ queryKey: ['alerts'] });
    } catch { }
  };

  const getRoleLabel = () => {
    switch (profile?.role) {
      case 'superadmin': return 'Superadmin';
      case 'admin': return 'Admin';
      default: return t('User', 'Usuario');
    }
  };

  if (!profile) return null;

  return (
    <>
      <Toaster
        position="bottom-right"
        toastOptions={{ className: 'dark:bg-gray-800 dark:text-white border dark:border-gray-700' }}
      />
      <div className="flex min-h-screen w-full bg-[#fcfcfc] dark:bg-gray-900 overflow-hidden text-gray-900 dark:text-gray-100 transition-colors duration-200 flex-col md:flex-row">

        {/* ── Sidebar ── */}
        <aside className={`${isSidebarOpen ? 'md:w-64' : 'md:w-20'} w-full border-b md:border-b-0 md:border-r border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-800 flex flex-col transition-all duration-300 ease-in-out`}>
          <div className="p-4 flex items-center justify-between border-b border-gray-50 dark:border-gray-700">
            <div className={`flex items-center gap-3 font-bold text-gray-800 dark:text-gray-100 overflow-hidden ${!isSidebarOpen && 'hidden'}`}>
              <img src="/ausarta.png" alt="Ausarta Logo" className="h-8 w-auto object-contain dark:invert" />
              <div className="flex flex-col">
                <span className="text-lg leading-none tracking-tight">Ausarta</span>
                <span className="text-[10px] text-gray-400 font-normal">Voice AI v2.0</span>
              </div>
            </div>
            <button
              onClick={() => setIsSidebarOpen(!isSidebarOpen)}
              className="p-1 hover:bg-gray-50 dark:hover:bg-gray-700 rounded text-gray-400 dark:text-gray-500"
            >
              {isSidebarOpen ? <PanelLeftClose size={18} /> : <PanelLeftOpen size={18} />}
            </button>
          </div>

          <nav className="flex-1 overflow-y-auto px-3 py-2 space-y-1">
            {hasPermission('overview') && (
              <SidebarItem icon={<LayoutDashboard size={18} />} label={t('Dashboard')} to="/" end collapsed={!isSidebarOpen} />
            )}

            <div className={`mt-6 mb-2 px-3 text-[10px] uppercase tracking-wider font-bold text-gray-400 ${!isSidebarOpen && 'hidden'}`}>
              {t('Build', 'Construcción')}
            </div>

            {isPlatformOwner && hasPermission('empresas') && (
              <SidebarItem icon={<Building2 size={18} />} label={t('Companies', 'Empresas')} to="/empresas" collapsed={!isSidebarOpen} />
            )}
            {hasPermission('agents') && (
              <SidebarItem icon={<Bot size={18} />} label={t('Agentes', 'Agentes')} to="/agents" collapsed={!isSidebarOpen} />
            )}
            {hasPermission('test-call') && (
              <SidebarItem icon={<Phone size={18} />} label={t('Test Call', 'Llamada Prueba')} to="/test-call" collapsed={!isSidebarOpen} />
            )}
            {hasPermission('campaigns') && (
              <SidebarItem icon={<Megaphone size={18} />} label={t('Campaigns', 'Campañas')} to="/campaigns" collapsed={!isSidebarOpen} />
            )}

            <div className={`mt-6 mb-2 px-3 text-[10px] uppercase tracking-wider font-bold text-gray-400 ${!isSidebarOpen && 'hidden'}`}>
              {t('Analysis', 'Análisis')}
            </div>

            {hasPermission('results') && (
              <SidebarItem icon={<BarChart3 size={18} />} label={t('Results', 'Resultados')} to="/results" collapsed={!isSidebarOpen} />
            )}
            {hasPermission('assistant') && (
              <SidebarItem icon={<BotMessageSquare size={18} />} label={t('Ausarta Copilot', 'Ausarta Copilot')} to="/copilot" collapsed={!isSidebarOpen} />
            )}
            {hasPermission('usage') && (
              <SidebarItem icon={<Zap size={18} />} label={t('Usage', 'Uso')} to="/usage" collapsed={!isSidebarOpen} />
            )}
            {hasPermission('admin') && (
              <SidebarItem icon={<Settings size={18} />} label={t('Admin', 'Administración')} to="/admin" collapsed={!isSidebarOpen} />
            )}
            {hasPermission('crm') && (
              <SidebarItem icon={<Share2 size={18} />} label={t('CRM Integration', 'Integración CRM')} to="/crm" collapsed={!isSidebarOpen} />
            )}
          </nav>

          {/* User info + Logout */}
          <div className="p-4 border-t border-gray-50 dark:border-gray-700 space-y-2">
            <div
              onClick={() => navigate('/profile')}
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

            {canSimulation && isSidebarOpen && (
              <div className="mx-2 mb-4 p-3 bg-indigo-50 dark:bg-indigo-900/10 border border-indigo-100 dark:border-indigo-800/50 rounded-xl space-y-3">
                <div className="flex items-center justify-between">
                  <p className="text-[9px] text-indigo-600 dark:text-indigo-400 font-bold uppercase tracking-wider">{t('Context Simulation')}</p>
                  {profile.role !== 'superadmin' && <div className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />}
                </div>

                <div className="flex gap-1">
                  {(['superadmin', 'admin', 'user'] as const)
                    .filter(r => realProfile?.role === 'superadmin' || isRootUser || r !== 'superadmin')
                    .map(r => (
                      <button
                        key={r}
                        title={r}
                        onClick={() => {
                          // If already viewing as this role, restore the natural role; otherwise switch to it
                          const isActive = profile?.role === r;
                          setSpoofedRole(isActive && r === realProfile?.role ? null : r);
                          toast.success(isActive && r === realProfile?.role ? t('Role restored', 'Rol restaurado') : `${t('Simulating', 'Simulando')} ${r}`);
                        }}
                        className={`text-[9px] flex-1 py-1 rounded transition-all font-bold ${profile?.role === r ? 'bg-indigo-600 text-white shadow-sm' : 'bg-white dark:bg-gray-800 text-gray-500 hover:bg-indigo-50'}`}
                      >
                        {r.charAt(0).toUpperCase()}
                      </button>
                    ))}
                </div>

                <select
                  value={profile?.empresa_id || ''}
                  onChange={e => {
                    const val = e.target.value === '' ? null : Number(e.target.value);
                    // Only clear empresa spoof if returning to own company; never auto-change the role
                    setSpoofedEmpresa(val === realProfile?.empresa_id ? null : val);
                    if (val === realProfile?.empresa_id || val === null) setSpoofedEmpresa(null);
                    toast.success(t('Viewing company context', 'Viendo contexto de empresa'));
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
                    onClick={() => { setSpoofedRole(null); setSpoofedEmpresa(null); toast.success(t('Context restored')); }}
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
                {isSidebarOpen && t('Logout')}
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
                {(['es', 'en', 'eu', 'gl'] as const).map(lang => (
                  <button
                    key={lang}
                    onClick={() => i18n.changeLanguage(lang)}
                    className={`text-xs px-2 py-1 rounded transition-colors ${i18n.language.startsWith(lang) ? 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 font-bold' : 'text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700'}`}
                  >
                    {lang.toUpperCase()}
                  </button>
                ))}
              </div>
            )}
          </div>
        </aside>

        {/* ── Main Content — renders the matched child route ── */}
        <main className={`flex-1 overflow-y-auto p-4 md:p-8 relative transition-all duration-300 ${isChatOpen ? 'mr-0 sm:mr-[400px]' : 'mr-0'}`}>
          <div className="w-full max-w-6xl mx-auto">
            {alerts.filter((a: any) => !hiddenAlerts.has(a.id)).length > 0 && (
              <div className="mb-6 space-y-2">
                {alerts
                  .filter((a: any) => !hiddenAlerts.has(a.id))
                  .map((alert: any) => (
                    <div key={alert.id} className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-400 p-4 rounded-xl flex items-center justify-between shadow-sm">
                      <div className="flex items-center gap-3">
                        <div className="bg-red-100 dark:bg-red-800/40 p-2 rounded-full">
                          <Zap className="w-5 h-5 text-red-600 dark:text-red-400" />
                        </div>
                        <div>
                          <p className="font-bold text-sm">{alert.type === 'error' ? t('Critical System Error', 'Error Crítico del Sistema') : t('System Alert', 'Alerta del Sistema')}</p>
                          <p className="text-xs opacity-80">{alert.message}</p>
                        </div>
                      </div>
                      <button
                        onClick={() => {
                          setHiddenAlerts(prev => new Set([...prev, alert.id]));
                          resolveAlert(alert.id);
                        }}
                        className="text-xs font-bold hover:underline"
                      >
                        {t('Resolve', 'Resolver')}
                      </button>
                    </div>
                  ))}
              </div>
            )}

            {/* Child route renders here */}
            <Suspense fallback={<ViewLoader />}>
              <Outlet />
            </Suspense>
          </div>

          {!isChatOpen && (
            <button
              onClick={() => setIsChatOpen(true)}
              className="fixed bottom-8 right-8 w-16 h-16 bg-blue-600 text-white rounded-full flex items-center justify-center shadow-2xl hover:bg-blue-700 transition-all hover:scale-110 active:scale-95 z-40 group overflow-hidden"
            >
              <div className="absolute inset-0 bg-blue-500 rounded-full animate-ping opacity-20 pointer-events-none group-hover:block" />
              <Bot size={28} />
            </button>
          )}
        </main>

        <AssistantPanel isOpen={isChatOpen} onClose={() => setIsChatOpen(false)} />

        {isCalling && (
          <Suspense fallback={null}>
            <LiveCallView onClose={() => setIsCalling(false)} />
          </Suspense>
        )}
      </div>
    </>
  );
};

export default AppShell;
