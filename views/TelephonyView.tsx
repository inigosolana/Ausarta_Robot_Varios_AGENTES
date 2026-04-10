import React, { useState, useEffect } from 'react';
import {
  ChevronDown, AlertTriangle, Trash2,
  Server, Eye, EyeOff, Wifi, WifiOff,
  Save, Loader2, CheckCircle2, XCircle,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { apiFetch } from '../lib/apiFetch';

// ── Types ─────────────────────────────────────────────────────────────────────

interface YeastarConfig {
  id?: string;
  api_url: string;
  api_port: number;
  api_username: string;
  is_active: boolean;
  created_at?: string;
  updated_at?: string;
}

interface YeastarForm extends YeastarConfig {
  api_password: string;
}

const EMPTY_FORM: YeastarForm = {
  api_url: '',
  api_port: 8088,
  api_username: '',
  api_password: '',
  is_active: true,
};

// ── Component ─────────────────────────────────────────────────────────────────

const TelephonyView: React.FC = () => {
  const { t } = useTranslation();

  // ── Yeastar state ──────────────────────────────────────────────────────────
  const [form, setForm] = useState<YeastarForm>(EMPTY_FORM);
  const [savedConfig, setSavedConfig] = useState<YeastarConfig | null>(null);
  const [showPassword, setShowPassword] = useState(false);
  const [loadingConfig, setLoadingConfig] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  // ── Load existing config on mount ─────────────────────────────────────────
  useEffect(() => {
    const load = async () => {
      try {
        const res = await apiFetch('/api/telephony/yeastar');
        if (res.status === 204 || res.status === 404) {
          // No config saved yet
          setLoadingConfig(false);
          return;
        }
        if (res.ok) {
          const data: YeastarConfig = await res.json();
          setSavedConfig(data);
          setForm({
            api_url: data.api_url,
            api_port: data.api_port,
            api_username: data.api_username,
            api_password: '',   // never returned by the API
            is_active: data.is_active,
          });
        }
      } catch (err) {
        console.error('[Yeastar] Error loading config:', err);
      } finally {
        setLoadingConfig(false);
      }
    };
    load();
  }, []);

  const handleChange = (field: keyof YeastarForm, value: string | number | boolean) => {
    setForm(prev => ({ ...prev, [field]: value }));
    setTestResult(null);
    setSaveSuccess(false);
  };

  // ── Test connection ────────────────────────────────────────────────────────
  const handleTest = async () => {
    if (!form.api_url || !form.api_username) return;
    setTesting(true);
    setTestResult(null);
    try {
      const res = await apiFetch('/api/telephony/yeastar/test', {
        method: 'POST',
        body: JSON.stringify({
          api_url: form.api_url,
          api_port: form.api_port,
          api_username: form.api_username,
          api_password: form.api_password || '<<unchanged>>',
        }),
      });
      const data = await res.json();
      setTestResult({ ok: data.ok, message: data.message });
    } catch (err) {
      setTestResult({ ok: false, message: t('Connection error', 'Error de conexión con el servidor') });
    } finally {
      setTesting(false);
    }
  };

  // ── Save config ────────────────────────────────────────────────────────────
  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.api_url || !form.api_username) return;
    setSaving(true);
    setSaveSuccess(false);
    try {
      const res = await apiFetch('/api/telephony/yeastar', {
        method: 'POST',
        body: JSON.stringify({
          api_url: form.api_url,
          api_port: form.api_port,
          api_username: form.api_username,
          api_password: form.api_password,
          is_active: form.is_active,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const saved: YeastarConfig = await res.json();
      setSavedConfig(saved);
      setForm(prev => ({ ...prev, api_password: '' }));
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 4000);
    } catch (err) {
      console.error('[Yeastar] Save error:', err);
    } finally {
      setSaving(false);
    }
  };

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="space-y-6 max-w-3xl">
      {/* Header */}
      <header>
        <h1 className="text-2xl font-bold text-gray-900">
          {t('Telephony Configuration', 'Configuración de Telefonía')}
        </h1>
        <p className="text-gray-500 text-sm mt-1">
          {t('Configure your telephony provider for outbound calls.', 'Configura tu proveedor de telefonía para llamadas salientes.')}
        </p>
      </header>

      {/* ── Generic provider card ────────────────────────────────────────── */}
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-8 space-y-6">
        <div>
          <label className="block text-sm font-semibold text-gray-800 mb-2">
            {t('Telephony Provider', 'Proveedor de Telefonía')}
          </label>
          <div className="relative">
            <select className="w-full h-10 px-4 pr-10 appearance-none bg-white border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/10 focus:border-blue-500 transition-all cursor-pointer">
              <option>LCR (Generic SIP / Asterisk)</option>
            </select>
            <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" size={16} />
          </div>
        </div>

        <div className="bg-gray-50/50 rounded-lg p-4 border border-gray-100">
          <h3 className="text-sm font-semibold text-gray-800 mb-1">
            {t('LCR Configuration', 'Configuración LCR')}
          </h3>
          <p className="text-xs text-gray-500 leading-relaxed">
            {t(
              'Using local Asterisk/LCR trunk. No additional credentials required here. Ensure your docker-compose is configured with proper Asterisk/ARI environment variables.',
              'Usando el troncal local Asterisk/LCR. No se requieren credenciales adicionales aquí. Asegúrate de que tu docker-compose esté configurado con las variables de entorno de Asterisk/ARI adecuadas.'
            )}
          </p>
        </div>

        <div>
          <label className="block text-sm font-semibold text-gray-800 mb-2">
            {t('From Numbers (Comma separated)', 'Números de Origen (Separados por coma)')}
          </label>
          <input
            type="text"
            placeholder={t('e.g. +34944771453, +34988...', 'ej: +34944771453, +34988...')}
            className="w-full h-10 px-4 bg-white border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/10 focus:border-blue-500 transition-all"
          />
          <p className="text-[11px] text-gray-400 mt-2">
            {t('Numbers that will appear as Caller ID.', 'Números que aparecerán como identificador de llamada (Caller ID).')}
          </p>
        </div>

        <div className="flex justify-end pt-4">
          <button className="px-6 py-2.5 bg-[#121212] text-white text-sm font-medium rounded-lg hover:bg-black transition-colors shadow-sm">
            {t('Save Configuration', 'Guardar Configuración')}
          </button>
        </div>
      </div>

      {/* ── Yeastar PBX Integration card ─────────────────────────────────── */}
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        {/* Card header */}
        <div className="px-8 py-5 border-b border-gray-100 bg-gradient-to-r from-indigo-50 to-blue-50 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="bg-indigo-100 p-2.5 rounded-xl">
              <Server size={18} className="text-indigo-600" />
            </div>
            <div>
              <h2 className="font-bold text-gray-900">
                {t('Yeastar PBX Integration', 'Integración Yeastar PBX')}
              </h2>
              <p className="text-xs text-gray-500 mt-0.5">
                {t(
                  'Connect your Yeastar S-Series or P-Series PBX via REST API.',
                  'Conecta tu centralita Yeastar S-Series o P-Series mediante la API REST.'
                )}
              </p>
            </div>
          </div>

          {/* Connection status badge */}
          {!loadingConfig && (
            savedConfig?.is_active ? (
              <span className="flex items-center gap-1.5 text-xs font-semibold text-emerald-700 bg-emerald-50 border border-emerald-200 px-3 py-1 rounded-full">
                <Wifi size={13} /> {t('Configured', 'Configurado')}
              </span>
            ) : (
              <span className="flex items-center gap-1.5 text-xs font-semibold text-gray-400 bg-gray-50 border border-gray-200 px-3 py-1 rounded-full">
                <WifiOff size={13} /> {t('Not configured', 'Sin configurar')}
              </span>
            )
          )}
        </div>

        {/* Form body */}
        <form onSubmit={handleSave} className="p-8 space-y-5">
          {loadingConfig ? (
            <div className="flex items-center justify-center py-12 gap-3 text-gray-400">
              <Loader2 size={22} className="animate-spin" />
              <span className="text-sm">{t('Loading configuration...', 'Cargando configuración...')}</span>
            </div>
          ) : (
            <>
              {/* Row 1: Host + Port */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <div className="sm:col-span-2">
                  <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">
                    {t('Host / IP', 'Host / IP')} *
                  </label>
                  <input
                    type="text"
                    required
                    value={form.api_url}
                    onChange={e => handleChange('api_url', e.target.value)}
                    placeholder="192.168.1.100"
                    className="w-full h-10 px-4 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400/20 focus:border-indigo-400 transition-all"
                  />
                  <p className="text-[11px] text-gray-400 mt-1">
                    {t('IP address or hostname of the Yeastar PBX.', 'IP o hostname de la centralita Yeastar.')}
                  </p>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">
                    {t('API Port', 'Puerto API')}
                  </label>
                  <input
                    type="number"
                    min={1}
                    max={65535}
                    required
                    value={form.api_port}
                    onChange={e => handleChange('api_port', parseInt(e.target.value) || 8088)}
                    className="w-full h-10 px-4 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400/20 focus:border-indigo-400 transition-all"
                  />
                  <p className="text-[11px] text-gray-400 mt-1">{t('Default: 8088', 'Por defecto: 8088')}</p>
                </div>
              </div>

              {/* Row 2: Username + Password */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">
                    {t('API Username', 'Usuario API')} *
                  </label>
                  <input
                    type="text"
                    required
                    autoComplete="off"
                    value={form.api_username}
                    onChange={e => handleChange('api_username', e.target.value)}
                    placeholder="admin"
                    className="w-full h-10 px-4 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400/20 focus:border-indigo-400 transition-all"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">
                    {t('API Password', 'Contraseña API')}
                    {savedConfig && (
                      <span className="ml-2 text-gray-400 normal-case font-normal">
                        ({t('leave blank to keep current', 'déjala vacía para conservar la actual')})
                      </span>
                    )}
                  </label>
                  <div className="relative">
                    <input
                      type={showPassword ? 'text' : 'password'}
                      autoComplete="new-password"
                      value={form.api_password}
                      onChange={e => handleChange('api_password', e.target.value)}
                      placeholder={savedConfig ? '••••••••' : t('Enter password', 'Introduce la contraseña')}
                      required={!savedConfig}
                      className="w-full h-10 pl-4 pr-11 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400/20 focus:border-indigo-400 transition-all"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword(v => !v)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 transition-colors"
                    >
                      {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>
                </div>
              </div>

              {/* Active toggle */}
              <div className="flex items-center gap-3 pt-1">
                <button
                  type="button"
                  onClick={() => handleChange('is_active', !form.is_active)}
                  className={`relative w-10 h-6 rounded-full transition-colors ${form.is_active ? 'bg-indigo-600' : 'bg-gray-300'}`}
                >
                  <span className={`absolute top-1 w-4 h-4 rounded-full bg-white transition-all shadow ${form.is_active ? 'right-1' : 'left-1'}`} />
                </button>
                <span className="text-sm text-gray-600">
                  {form.is_active
                    ? t('Integration enabled', 'Integración habilitada')
                    : t('Integration disabled', 'Integración deshabilitada')
                  }
                </span>
              </div>

              {/* Test result banner */}
              {testResult && (
                <div className={`flex items-start gap-3 p-4 rounded-xl border text-sm ${
                  testResult.ok
                    ? 'bg-emerald-50 border-emerald-200 text-emerald-800'
                    : 'bg-red-50 border-red-200 text-red-700'
                }`}>
                  {testResult.ok
                    ? <CheckCircle2 size={18} className="text-emerald-500 shrink-0 mt-0.5" />
                    : <XCircle size={18} className="text-red-500 shrink-0 mt-0.5" />
                  }
                  <span>{testResult.message}</span>
                </div>
              )}

              {/* Save success banner */}
              {saveSuccess && (
                <div className="flex items-center gap-3 p-4 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-800 text-sm">
                  <CheckCircle2 size={18} className="text-emerald-500 shrink-0" />
                  {t('Configuration saved successfully.', 'Configuración guardada correctamente.')}
                </div>
              )}

              {/* Action buttons */}
              <div className="flex items-center justify-between pt-2 border-t border-gray-100">
                <button
                  type="button"
                  onClick={handleTest}
                  disabled={testing || !form.api_url || !form.api_username}
                  className="flex items-center gap-2 px-5 h-10 border border-indigo-200 bg-indigo-50 hover:bg-indigo-100 text-indigo-700 rounded-xl text-sm font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  {testing ? (
                    <><Loader2 size={15} className="animate-spin" /> {t('Testing...', 'Probando...')}</>
                  ) : (
                    <><Wifi size={15} /> {t('Test Connection', 'Probar Conexión')}</>
                  )}
                </button>

                <button
                  type="submit"
                  disabled={saving || !form.api_url || !form.api_username}
                  className="flex items-center gap-2 px-6 h-10 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl text-sm font-semibold transition-colors disabled:opacity-40 disabled:cursor-not-allowed shadow-sm shadow-indigo-200"
                >
                  {saving ? (
                    <><Loader2 size={15} className="animate-spin" /> {t('Saving...', 'Guardando...')}</>
                  ) : (
                    <><Save size={15} /> {t('Save Configuration', 'Guardar Configuración')}</>
                  )}
                </button>
              </div>
            </>
          )}
        </form>
      </div>

      {/* ── System maintenance card ───────────────────────────────────────── */}
      <div className="bg-red-50 rounded-xl border border-red-100 p-8 space-y-4">
        <div>
          <h3 className="text-sm font-bold text-red-800 flex items-center gap-2">
            <AlertTriangle size={18} />
            {t('System Maintenance', 'Mantenimiento del Sistema')}
          </h3>
          <p className="text-xs text-red-600 mt-1 uppercase tracking-wider font-bold opacity-70">
            {t('Extreme Cleanup', 'Limpieza Extrema')}
          </p>
        </div>
        <p className="text-sm text-red-700">
          {t(
            'If the system hangs with the message "Calls in progress" and the agent does not respond, you can force the cleanup of all active rooms. This will hang up all current calls.',
            'Si el sistema se queda bloqueado con el mensaje "Hay llamadas en curso" y el agente no responde, puedes forzar la limpieza de todas las salas activas. Esto colgará todas las llamadas actuales.'
          )}
        </p>
        <div className="flex justify-start">
          <button
            onClick={async () => {
              if (window.confirm(t(
                'Are you sure you want to force close ALL active calls? This will unlock the system.',
                '¿Estás seguro de que quieres forzar el cierre de TODAS las llamadas activas? Esto desbloqueará el sistema.'
              ))) {
                try {
                  const res = await fetch(`${import.meta.env.VITE_API_URL || '/api'}/calls/cleanup`, { method: 'POST' });
                  if (res.ok) alert(t('✅ System cleaned successfully. All rooms have been cleared.', '✅ Sistema limpiado correctamente. Todas las salas han sido borradas.'));
                  else alert(t('❌ Error cleaning the rooms.', '❌ Error al limpiar las salas.'));
                } catch {
                  alert(t('Server connection error.', 'Error de conexión con el servidor.'));
                }
              }
            }}
            className="flex items-center gap-2 px-6 py-2.5 bg-red-600 text-white text-sm font-bold rounded-lg hover:bg-red-700 transition-colors shadow-sm"
          >
            <Trash2 size={18} />
            {t('Reset Rooms and Unlock System', 'Resetear Salas y Desbloquear Sistema')}
          </button>
        </div>
      </div>
    </div>
  );
};

export default TelephonyView;
