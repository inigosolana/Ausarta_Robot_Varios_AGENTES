import React, { useState, useEffect } from 'react';
import {
  ChevronDown, AlertTriangle, Trash2, Building2,
  Server, Eye, EyeOff, Wifi, WifiOff,
  Save, Loader2, CheckCircle2, XCircle, Info
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { apiFetch } from '../lib/apiFetch';
import { useAuth } from '../contexts/AuthContext';
import { supabase } from '../lib/supabase';
import type { Empresa } from '../types';

// ── Types ─────────────────────────────────────────────────────────────────────

interface YeastarConfig {
  empresa_id?: number;
  yeastar_pbx_url: string;
  yeastar_client_id: string;
  yeastar_client_secret?: string; // only for form input or '********'
}

const EMPTY_FORM: YeastarConfig = {
  yeastar_pbx_url: '',
  yeastar_client_id: '',
  yeastar_client_secret: '',
};

// ── Component ─────────────────────────────────────────────────────────────────

const TelephonyView: React.FC = () => {
  const { t } = useTranslation();
  const { profile, isPlatformOwner } = useAuth();

  // ── Yeastar state ──────────────────────────────────────────────────────────
  const [form, setForm] = useState<YeastarConfig>(EMPTY_FORM);
  const [savedConfig, setSavedConfig] = useState<YeastarConfig | null>(null);
  const [showPassword, setShowPassword] = useState(false);
  const [loadingConfig, setLoadingConfig] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  // ── Multi-tenant state ─────────────────────────────────────────────────────
  const [empresas, setEmpresas] = useState<Empresa[]>([]);
  const [selectedEmpresaId, setSelectedEmpresaId] = useState<number | null>(null);
  /** IP desde backend (.env AUSARTA_PUBLIC_IP) — no depende del build Vite */
  const [ausartaPublicIp, setAusartaPublicIp] = useState(
    () => (import.meta.env.VITE_AUSARTA_PUBLIC_IP as string | undefined)?.trim() || '',
  );

  useEffect(() => {
    apiFetch('/api/telephony/platform-info')
      .then(async (res) => {
        if (!res.ok) return;
        const data = await res.json();
        const ip = String(data?.ausarta_public_ip || '').trim();
        if (ip) setAusartaPublicIp(ip);
      })
      .catch(() => {
        /* silencioso: se usa fallback VITE_ o placeholder */
      });
  }, []);

  useEffect(() => {
    if (isPlatformOwner) {
      loadEmpresas();
    } else if (profile?.empresa_id) {
      setSelectedEmpresaId(profile.empresa_id);
    } else {
      setLoadingConfig(false);
    }
  }, [profile, isPlatformOwner]);

  useEffect(() => {
    if (selectedEmpresaId) {
      loadConfig(selectedEmpresaId);
    } else {
      setForm(EMPTY_FORM);
      setSavedConfig(null);
    }
  }, [selectedEmpresaId]);

  const loadEmpresas = async () => {
    const { data, error } = await supabase.from('empresas').select('*').order('nombre');
    if (!error && data) {
      setEmpresas(data);
      if (data.length > 0 && !selectedEmpresaId) {
        setSelectedEmpresaId(data[0].id);
      }
    }
  };

  const loadConfig = async (empId: number) => {
    setLoadingConfig(true);
    setTestResult(null);
    setSaveSuccess(false);
    try {
      const res = await apiFetch(`/api/telephony/yeastar?empresa_id=${empId}`);
      if (res.status === 204 || res.status === 404) {
        setSavedConfig(null);
        setForm(EMPTY_FORM);
        return;
      }
      if (res.ok) {
        const data: YeastarConfig = await res.json();
        setSavedConfig(data);
        setForm({
          yeastar_pbx_url: data.yeastar_pbx_url || '',
          yeastar_client_id: data.yeastar_client_id || '',
          yeastar_client_secret: '',   // handled dynamically on save
        });
      }
    } catch (err) {
      console.error('[Yeastar] Error loading config:', err);
    } finally {
      setLoadingConfig(false);
    }
  };

  const handleChange = (field: keyof YeastarConfig, value: string) => {
    setForm(prev => ({ ...prev, [field]: value }));
    setTestResult(null);
    setSaveSuccess(false);
  };

  // ── Test connection ────────────────────────────────────────────────────────
  const handleTest = async () => {
    if (!form.yeastar_pbx_url || !form.yeastar_client_id || !selectedEmpresaId) return;
    setTesting(true);
    setTestResult(null);
    try {
      const payload = {
        empresa_id: selectedEmpresaId,
        yeastar_pbx_url: form.yeastar_pbx_url,
        yeastar_client_id: form.yeastar_client_id,
        yeastar_client_secret: form.yeastar_client_secret || '********',
      };
      const res = await apiFetch('/api/telephony/yeastar/test', {
        method: 'POST',
        body: JSON.stringify(payload),
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
    if (!form.yeastar_pbx_url || !form.yeastar_client_id || !selectedEmpresaId) return;
    setSaving(true);
    setSaveSuccess(false);
    try {
      const payload: any = {
        empresa_id: selectedEmpresaId,
        yeastar_pbx_url: form.yeastar_pbx_url,
        yeastar_client_id: form.yeastar_client_id,
      };

      // UX: Only send the secret if it's not empty and not the masked placeholder
      if (form.yeastar_client_secret && form.yeastar_client_secret !== '********') {
        payload.yeastar_client_secret = form.yeastar_client_secret;
      }

      const res = await apiFetch('/api/telephony/yeastar', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const saved: YeastarConfig = await res.json();
      setSavedConfig(saved);
      setForm(prev => ({ ...prev, yeastar_client_secret: '' }));
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
    <div className="space-y-6 max-w-4xl mx-auto">
      {/* Header */}
      <header>
        <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
          <Server size={24} className="text-indigo-600" />
          {t('Telephony Configuration', 'Configuración de Telefonía PBX')}
        </h1>
        <p className="text-gray-500 text-sm mt-1">
          {t('Configure your telephony provider for outbound calls and transfers.', 'Configura tu proveedor de telefonía para llamadas salientes y transferencias.')}
        </p>
      </header>

      {/* Empresa Selector */}
      {isPlatformOwner && (
        <div className="mb-6">
          <label className="block text-sm font-medium text-gray-700 mb-2 flex items-center gap-2">
            <Building2 size={15} />
            {t('Company to configure', 'Empresa a configurar')}
          </label>
          <select
            value={selectedEmpresaId || ''}
            onChange={(e) => setSelectedEmpresaId(Number(e.target.value))}
            className="w-full h-10 px-3 rounded-lg border border-gray-200 bg-white text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 outline-none"
          >
            <option value="" disabled>{t('Select a company', 'Selecciona una empresa')}</option>
            {empresas.map(emp => (
              <option key={emp.id} value={emp.id}>{emp.nombre}</option>
            ))}
          </select>
        </div>
      )}

      {/* ── Yeastar PBX Integration card ─────────────────────────────────── */}
      {!selectedEmpresaId ? (
          <div className="bg-white rounded-2xl border border-gray-100 p-10 text-center text-gray-400 shadow-sm">
              {t('Select a company to configure telephony.', 'Selecciona una empresa para configurar la telefonía.')}
          </div>
      ) : (
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        {/* Card header */}
        <div className="px-8 py-5 border-b border-gray-100 bg-gradient-to-r from-indigo-50 to-blue-50 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="bg-indigo-100 p-2.5 rounded-xl">
              <Server size={18} className="text-indigo-600" />
            </div>
            <div>
              <h2 className="font-bold text-gray-900">
                {t('Yeastar P-Series Integration', 'Integración Yeastar P-Series')}
              </h2>
              <p className="text-xs text-gray-500 mt-0.5">
                {t(
                  'Connect your Yeastar P-Series PBX via REST API v2.0.',
                  'Conecta tu centralita Yeastar P-Series mediante la API REST v2.0.'
                )}
              </p>
            </div>
          </div>

          {/* Connection status badge */}
          {!loadingConfig && (
            savedConfig?.yeastar_pbx_url ? (
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

        {/* Instrucciones API Yeastar — permisos mínimos (Extension GET + Call Control POST) */}
        <div className="px-8 py-6 bg-blue-50 border-b border-blue-100">
          <h3 className="flex items-center gap-2 text-sm font-bold text-blue-900 mb-3">
            <Info size={16} className="text-blue-600 shrink-0" />
            Instrucciones para el técnico de Yeastar
          </h3>
          <div className="text-sm text-blue-900/90 space-y-3 leading-relaxed">
            <p>
              Entra al panel de administración de Yeastar P-Series y ve a{' '}
              <strong>Integraciones → API</strong>. Crea una nueva conexión con esta configuración:
            </p>
            <ol className="list-decimal list-inside space-y-3 pl-0.5">
              <li>
                <strong>Privilegios (API Interfaces):</strong> Marca ÚNICAMENTE estas dos casillas (por
                seguridad mínima):
                <ul className="list-none mt-2 ml-4 space-y-1.5 text-blue-800/90">
                  <li>
                    • Fila <strong>Extension</strong>: Marca <strong>GET</strong>{' '}
                    <em className="text-blue-700/80">(Para consultar si la extensión está libre).</em>
                  </li>
                  <li>
                    • Fila <strong>Call Control</strong>: Marca <strong>POST</strong>{' '}
                    <em className="text-blue-700/80">(Para ejecutar la transferencia de llamada).</em>
                  </li>
                </ul>
              </li>
              <li>
                <strong>IP Permitida:</strong>{' '}
                {ausartaPublicIp ? (
                  <code className="bg-blue-100 px-2 py-0.5 rounded font-mono text-blue-950 font-semibold">
                    {ausartaPublicIp}
                  </code>
                ) : (
                  <code className="bg-amber-100 border border-amber-200 px-2 py-0.5 rounded font-mono text-amber-900 font-semibold">
                    [PONER_AQUI_LA_IP_DE_AUSARTA]
                  </code>
                )}{' '}
                <em className="text-blue-700/80">(La IP pública de este servidor)</em>
                {!ausartaPublicIp && (
                  <span className="block mt-1.5 text-xs text-amber-800/90">
                    Añade <code className="bg-amber-50 px-1 rounded">AUSARTA_PUBLIC_IP=15.218.15.30</code>{' '}
                    en el <strong>.env del backend</strong> (contenedor <code>backend</code> en Portainer) y
                    reinicia solo el backend. No hace falta rebuild del frontend.
                  </span>
                )}
              </li>
              <li>
                <strong>Máscara de subred:</strong>{' '}
                <code className="bg-blue-100 px-1.5 py-0.5 rounded font-mono">255.255.255.255</code>
              </li>
            </ol>
            <p className="pt-1 border-t border-blue-200/60">
              Una vez guardado, copia el <strong>Client ID</strong> y <strong>Client Secret</strong>{' '}
              generados y pégalos aquí abajo.
            </p>
          </div>
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
              {/* Row 1: Host URL */}
              <div>
                <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">
                  {t('PBX URL', 'URL de la Centralita')} *
                </label>
                <input
                  type="url"
                  required
                  value={form.yeastar_pbx_url}
                  onChange={e => handleChange('yeastar_pbx_url', e.target.value)}
                  placeholder="https://pbx.empresa.com:8088"
                  className="w-full h-10 px-4 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400/20 focus:border-indigo-400 transition-all"
                />
                <p className="text-[11px] text-gray-400 mt-1">
                  {t('Full URL including protocol and port.', 'URL completa incluyendo protocolo (http/https) y puerto.')}
                </p>
              </div>

              {/* Row 2: Client ID + Secret */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">
                    {t('Client ID', 'Client ID')} *
                  </label>
                  <input
                    type="text"
                    required
                    autoComplete="off"
                    value={form.yeastar_client_id}
                    onChange={e => handleChange('yeastar_client_id', e.target.value)}
                    placeholder="xxxxxxxxxxxxxxxx"
                    className="w-full h-10 px-4 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400/20 focus:border-indigo-400 transition-all"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">
                    {t('Client Secret', 'Client Secret')}
                    {savedConfig?.yeastar_pbx_url && (
                      <span className="ml-2 text-gray-400 normal-case font-normal">
                        ({t('leave blank to keep current', 'déjala vacía para conservar el actual')})
                      </span>
                    )}
                  </label>
                  <div className="relative">
                    <input
                      type={showPassword ? 'text' : 'password'}
                      autoComplete="new-password"
                      value={form.yeastar_client_secret}
                      onChange={e => handleChange('yeastar_client_secret', e.target.value)}
                      placeholder={savedConfig?.yeastar_pbx_url ? '••••••••' : t('Enter client secret', 'Introduce el secreto')}
                      required={!savedConfig?.yeastar_pbx_url}
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
                  disabled={testing || !form.yeastar_pbx_url || !form.yeastar_client_id}
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
                  disabled={saving || !form.yeastar_pbx_url || !form.yeastar_client_id}
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
      )}

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
                  const res = await fetch(`${(import.meta as any).env.VITE_API_URL || '/api'}/calls/cleanup`, { method: 'POST' });
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

