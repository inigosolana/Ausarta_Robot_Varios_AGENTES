import React, { useState, useEffect } from 'react';
import {
  ChevronDown, AlertTriangle, Trash2, Building2,
  Server, Eye, EyeOff, Wifi, WifiOff,
  Save, Loader2, CheckCircle2, XCircle, Info, Copy, Check
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { apiFetch } from '../lib/apiFetch';
import { useAuth } from '../contexts/AuthContext';
import type { Empresa } from '../types';

// ── Types ─────────────────────────────────────────────────────────────────────

interface YeastarConfig {
  empresa_id?: number;
  yeastar_pbx_url: string;
  yeastar_api_mode: 'pseries' | 'cloud_pbx';
  yeastar_client_id: string;
  yeastar_client_secret?: string; // only for form input or '********'
  enabled_capabilities?: string[];
}

interface YeastarCapability {
  id: string;
  group: string;
  label: string;
  description: string;
  permission: string;
  endpoints: string[];
  status: 'implemented' | 'available' | 'planned' | string;
}

const EMPTY_FORM: YeastarConfig = {
  yeastar_pbx_url: '',
  yeastar_api_mode: 'pseries',
  yeastar_client_id: '',
  yeastar_client_secret: '',
  enabled_capabilities: [],
};

// ── Component ─────────────────────────────────────────────────────────────────

const formatApiError = (detail: unknown, fallback: string) => {
  if (!detail) return fallback;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item: any) => {
        const path = Array.isArray(item?.loc) ? item.loc.join('.') : '';
        const msg = item?.msg || item?.message || JSON.stringify(item);
        return path ? `${path}: ${msg}` : msg;
      })
      .join(' | ');
  }
  if (typeof detail === 'object') {
    const data = detail as any;
    return data.message || data.msg || data.error || JSON.stringify(data);
  }
  return String(detail);
};

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
  const [saveError, setSaveError] = useState('');
  const [capabilities, setCapabilities] = useState<YeastarCapability[]>([]);
  const [capabilitiesLoading, setCapabilitiesLoading] = useState(false);

  // ── Multi-tenant state ─────────────────────────────────────────────────────
  const [empresas, setEmpresas] = useState<Empresa[]>([]);
  const [selectedEmpresaId, setSelectedEmpresaId] = useState<number | null>(null);
  /** IP desde backend (.env AUSARTA_PUBLIC_IP) — no depende del build Vite */
  const [ausartaPublicIp, setAusartaPublicIp] = useState(
    () => (import.meta.env.VITE_AUSARTA_PUBLIC_IP as string | undefined)?.trim() || '',
  );
  const [yeastarWebhookUrl, setYeastarWebhookUrl] = useState('');
  const [webhookCopied, setWebhookCopied] = useState(false);
  const isCloudMode = form.yeastar_api_mode === 'cloud_pbx';
  const currentModeLabel = isCloudMode ? 'Cloud PBX' : 'P-Series';
  const currentCredentialLabel = isCloudMode ? 'API Username' : 'Client ID';
  const currentSecretLabel = isCloudMode ? 'API Password' : 'Client Secret';

  useEffect(() => {
    apiFetch('/api/telephony/platform-info')
      .then(async (res) => {
        if (!res.ok) return;
        const data = await res.json();
        const ip = String(data?.ausarta_public_ip || '').trim();
        if (ip) setAusartaPublicIp(ip);
        const webhook = String(data?.yeastar_webhook_url || '').trim();
        if (webhook) {
          setYeastarWebhookUrl(webhook);
        } else if (typeof window !== 'undefined') {
          setYeastarWebhookUrl(`${window.location.origin}/webhooks/yeastar`);
        }
      })
      .catch(() => {
        if (typeof window !== 'undefined') {
          setYeastarWebhookUrl(`${window.location.origin}/webhooks/yeastar`);
        }
      });
  }, []);

  useEffect(() => {
    setCapabilitiesLoading(true);
    apiFetch('/api/telephony/yeastar/capabilities')
      .then(async (res) => {
        if (!res.ok) return;
        const data = await res.json();
        setCapabilities(data.capabilities || []);
      })
      .catch(() => setCapabilities([]))
      .finally(() => setCapabilitiesLoading(false));
  }, []);

  const copyWebhookUrl = async () => {
    if (!yeastarWebhookUrl) return;
    try {
      await navigator.clipboard.writeText(yeastarWebhookUrl);
      setWebhookCopied(true);
      setTimeout(() => setWebhookCopied(false), 2000);
    } catch {
      /* clipboard no disponible */
    }
  };

  useEffect(() => {
    if (isPlatformOwner) {
      loadEmpresas();
      return;
    }
    if (profile?.empresa_id) {
      setSelectedEmpresaId(profile.empresa_id);
      return;
    }
    setLoadingConfig(false);
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
    try {
      const res = await apiFetch('/api/admin/empresas');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: Empresa[] = await res.json();
      setEmpresas(data || []);
      if (data?.length) {
        const ausarta = data.find(emp => emp.nombre?.toLowerCase() === 'ausarta');
        setSelectedEmpresaId(prev => prev ?? (ausarta?.id ?? data[0].id ?? null));
      }
    } catch (err) {
      console.error('[Telephony] Error loading empresas:', err);
      setEmpresas([]);
      setLoadingConfig(false);
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
          yeastar_api_mode: data.yeastar_api_mode || 'pseries',
          yeastar_client_id: data.yeastar_client_id || '',
          yeastar_client_secret: '',   // handled dynamically on save
          enabled_capabilities: data.enabled_capabilities || [],
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

  const toggleCapability = (capabilityId: string) => {
    setForm(prev => {
      const current = prev.enabled_capabilities || [];
      return {
        ...prev,
        enabled_capabilities: current.includes(capabilityId)
          ? current.filter(id => id !== capabilityId)
          : [...current, capabilityId],
      };
    });
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
        yeastar_api_mode: form.yeastar_api_mode,
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
    setSaveError('');
    try {
      const payload: any = {
        empresa_id: selectedEmpresaId,
        yeastar_pbx_url: form.yeastar_pbx_url,
        yeastar_api_mode: form.yeastar_api_mode,
        yeastar_client_id: form.yeastar_client_id,
        enabled_capabilities: form.enabled_capabilities || [],
      };

      // UX: Only send the secret if it's not empty and not the masked placeholder
      if (form.yeastar_client_secret && form.yeastar_client_secret !== '********') {
        payload.yeastar_client_secret = form.yeastar_client_secret;
      }

      const res = await apiFetch('/api/telephony/yeastar', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(formatApiError(errorData?.detail, `HTTP ${res.status}`));
      }
      const saved: YeastarConfig = await res.json();
      setSavedConfig(saved);
      setForm(prev => ({ ...prev, yeastar_client_secret: '', enabled_capabilities: saved.enabled_capabilities || [] }));
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 4000);
    } catch (err) {
      console.error('[Yeastar] Save error:', err);
      setSaveError(err instanceof Error ? err.message : t('Save error', 'Error al guardar la configuracion'));
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
                {t('Yeastar Integration', 'Integracion Yeastar')} {currentModeLabel}
              </h2>
              <p className="text-xs text-gray-500 mt-0.5">
                {t(
                  'Connect your Yeastar PBX using the correct API mode for this tenant.',
                  'Conecta la centralita Yeastar usando el modo de API correcto para esta empresa.'
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
              {isCloudMode ? (
                <>Modo legacy Cloud PBX. Usa usuario y contrasena API para el endpoint <strong>/api/v2.0.0/login</strong>.</>
              ) : (
                <>Entra al panel de administracion de Yeastar P-Series y ve a <strong>Integraciones / API</strong>. Crea una nueva conexion con esta configuracion:</>
              )}
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
                    Añade <code className="bg-amber-50 px-1 rounded">AUSARTA_PUBLIC_IP=tu.ip.publica</code>{' '}
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

        {/* Paso 2: Webhook Event Push (vincular callid ↔ encuesta / transferencias) */}
        <div className="px-8 py-6 bg-violet-50 border-b border-violet-100">
          <h3 className="flex items-center gap-2 text-sm font-bold text-violet-900 mb-3">
            <Info size={16} className="text-violet-600 shrink-0" />
            Paso 2 — Webhook Event Push (en el panel de Yeastar)
          </h3>
          <div className="text-sm text-violet-900/90 space-y-3 leading-relaxed">
            <p className="bg-white/60 border border-violet-200 rounded-lg px-3 py-2 text-xs">
              <strong>No confundas con el Paso 1 (API):</strong> el estado de extensión y la transferencia
              se hacen con <strong>Extension GET</strong> y <strong>Call Control POST</strong> en{' '}
              <em>Integraciones → API</em>. El webhook es solo para que Ausarta reciba el{' '}
              <strong>ID de la llamada</strong> (<code className="font-mono">call_id</code>) y pueda
              transferir correctamente.
            </p>
            <p>
              En <strong>Integraciones → Webhook</strong> (o Event Push), activa el checkbox y crea una fila:
            </p>
            <ul className="list-none space-y-3">
              <li>
                <strong>URL del webhook:</strong>
                <div className="mt-1.5 flex flex-wrap items-center gap-2">
                  <code className="flex-1 min-w-0 break-all bg-violet-100 px-2 py-1.5 rounded font-mono text-xs text-violet-950 font-semibold">
                    {yeastarWebhookUrl || 'https://tu-dominio-ausarta.com/webhooks/yeastar'}
                  </code>
                  {yeastarWebhookUrl && (
                    <button
                      type="button"
                      onClick={copyWebhookUrl}
                      className="shrink-0 inline-flex items-center gap-1.5 text-xs font-semibold text-violet-800 bg-white border border-violet-200 px-3 py-1.5 rounded-lg hover:bg-violet-100 transition-colors"
                    >
                      {webhookCopied ? <Check size={14} /> : <Copy size={14} />}
                      {webhookCopied ? 'Copiado' : 'Copiar URL'}
                    </button>
                  )}
                </div>
                <span className="block mt-1 text-xs text-violet-700/80">
                  Debe ser accesible desde Internet. Si tu Yeastar Cloud exige HTTPS, usa `https://...` en vez de `http://...`.
                </span>
              </li>
              <li>
                <strong>Secret:</strong> deja el que genere Yeastar (no hace falta pegarlo en Ausarta).
              </li>
              <li>
                <strong>Request Method:</strong>{' '}
                <code className="bg-violet-100 px-1.5 py-0.5 rounded font-mono">POST</code>
              </li>
              <li>
                <strong>Event (obligatorio):</strong> busca y marca{' '}
                <strong>30011 — Call State Changed</strong> (cambio de estado de llamada; trae{' '}
                <code className="font-mono text-xs">call_id</code>). Si el panel permite varias filas, una
                sola con 30011 basta.
                <ul className="list-none mt-2 ml-1 space-y-1 text-xs text-violet-800/90">
                  <li>
                    • <strong>30008 — Extension Call State Changed</strong> → solo Ringing/Busy/Idle de la
                    extensión; <em>no sustituye</em> la consulta Extension GET del Paso 1.
                  </li>
                  <li>
                    • <strong>30007 / 30009</strong> → registro y presencia; <em>no los necesitas</em> para
                    Ausarta.
                  </li>
                </ul>
              </li>
            </ul>

            <div className="pt-3 border-t border-violet-200/60">
              <p className="text-xs text-violet-900/80 font-semibold mb-2">
                Cómo confirmar que Ausarta está recibiendo el webhook
              </p>
              <ol className="list-decimal list-inside space-y-2 text-xs text-violet-900/80">
                <li>
                  En Yeastar, guarda la fila del webhook con evento <strong>30011</strong> y URL <strong>/webhooks/yeastar</strong>.
                  Si Yeastar tiene botón <em>Send test</em>, úsalo; si no, haz una llamada de prueba desde la extensión configurada.
                </li>
                <li>
                  En la tabla del webhook de Yeastar, revisa el <strong>historial/operaciones</strong>:
                  debe aparecer al menos un envío correcto (habitualmente respuesta OK).
                </li>
                <li>
                  En Ausarta, abre el contenedor <code>backend</code> en Portainer → <strong>Logs</strong>
                  y busca líneas como <code className="font-mono">[Yeastar Background] Evento</code>.
                </li>
                <li>
                  Si no aparece nada: verifica que la URL tenga exactamente <code className="font-mono">/webhooks/yeastar</code>
                  y que el firewall/router permita tráfico entrante por el puerto donde está Nginx (80/443).
                </li>
              </ol>
            </div>
            <p className="text-xs text-violet-700/80 pt-1 border-t border-violet-200/60">
              Si la URL no coincide con tu dominio, define{' '}
              <code className="bg-violet-100/80 px-1 rounded">FRONTEND_URL=https://app.tudominio.com</code>{' '}
              o <code className="bg-violet-100/80 px-1 rounded">AUSARTA_PUBLIC_WEBHOOK_BASE_URL</code> en el
              .env del backend y reinicia el contenedor.
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
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">
                    {t('API Mode', 'Modo de API')} *
                  </label>
                  <select
                    value={form.yeastar_api_mode}
                    onChange={e => handleChange('yeastar_api_mode', e.target.value)}
                    className="w-full h-10 px-4 border border-gray-200 rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-indigo-400/20 focus:border-indigo-400 transition-all"
                  >
                    <option value="pseries">Yeastar P-Series OpenAPI</option>
                    <option value="cloud_pbx">Yeastar Cloud PBX legacy</option>
                  </select>
                </div>
                <div className="rounded-xl border border-blue-100 bg-blue-50 px-4 py-2 text-xs text-blue-900">
                  {isCloudMode ? (
                    <>Cloud PBX legacy usa <code>/api/v2.0.0/login</code> y <code>/api/v2.0.0/extension/list</code>.</>
                  ) : (
                    <>P-Series OpenAPI usa <code>/openapi/v1.0/get_token</code> y endpoints <code>/openapi/v1.0</code>.</>
                  )}
                </div>
              </div>

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
                  placeholder={isCloudMode ? "https://pbx.empresa.cloud:443" : "https://pbx.empresa.com:8088"}
                  className="w-full h-10 px-4 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400/20 focus:border-indigo-400 transition-all"
                />
                <p className="text-[11px] text-gray-400 mt-1">
                  {isCloudMode ? 'URL completa de la instancia Cloud PBX. Si no indicas puerto, se usara 443.' : t('Full URL including protocol and port.', 'URL completa incluyendo protocolo (http/https) y puerto.')}
                </p>
              </div>

              {/* Row 2: Client ID + Secret */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">
                    {currentCredentialLabel} *
                  </label>
                  <input
                    type="text"
                    required
                    autoComplete="off"
                    value={form.yeastar_client_id}
                    onChange={e => handleChange('yeastar_client_id', e.target.value)}
                    placeholder={isCloudMode ? "api" : "xxxxxxxxxxxxxxxx"}
                    className="w-full h-10 px-4 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400/20 focus:border-indigo-400 transition-all"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">
                    {currentSecretLabel}
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
                      placeholder={savedConfig?.yeastar_pbx_url ? '********' : isCloudMode ? 'Introduce la API Password' : t('Enter client secret', 'Introduce el secreto')}
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

              <div className="space-y-3 pt-2">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-sm font-bold text-gray-900">Funciones API Yeastar</h3>
                    <p className="text-xs text-gray-500 mt-0.5">
                      Selecciona las capacidades que quieres habilitar para esta empresa.
                    </p>
                  </div>
                  <span className="rounded-full bg-gray-100 px-2 py-1 text-[11px] font-semibold text-gray-500">
                    {(form.enabled_capabilities || []).length} activas
                  </span>
                </div>

                {capabilitiesLoading ? (
                  <div className="flex items-center gap-2 rounded-xl border border-gray-100 bg-gray-50 px-4 py-3 text-sm text-gray-400">
                    <Loader2 size={15} className="animate-spin" />
                    Cargando funciones API...
                  </div>
                ) : (
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                    {capabilities.map(cap => {
                      const checked = (form.enabled_capabilities || []).includes(cap.id);
                      const badgeClass = cap.status === 'implemented'
                        ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                        : cap.status === 'planned'
                          ? 'bg-amber-50 text-amber-700 border-amber-200'
                          : 'bg-blue-50 text-blue-700 border-blue-200';
                      return (
                        <label
                          key={cap.id}
                          className={`block rounded-xl border p-4 cursor-pointer transition-colors ${
                            checked ? 'border-indigo-300 bg-indigo-50' : 'border-gray-100 hover:border-gray-200 bg-white'
                          }`}
                        >
                          <div className="flex items-start gap-3">
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() => toggleCapability(cap.id)}
                              className="mt-1 h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                            />
                            <div className="min-w-0 flex-1">
                              <div className="flex flex-wrap items-center gap-2">
                                <span className="text-sm font-bold text-gray-900">{cap.label}</span>
                                <span className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase ${badgeClass}`}>
                                  {cap.status === 'implemented' ? 'listo' : cap.status === 'planned' ? 'plan' : 'disponible'}
                                </span>
                              </div>
                              <p className="mt-1 text-xs text-gray-500">{cap.description}</p>
                              <p className="mt-2 text-[11px] font-semibold text-gray-500">
                                Permiso Yeastar: <span className="font-mono">{cap.permission}</span>
                              </p>
                              <div className="mt-2 flex flex-wrap gap-1">
                                {cap.endpoints.slice(0, 3).map(endpoint => (
                                  <code key={endpoint} className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-600">
                                    {endpoint}
                                  </code>
                                ))}
                                {cap.endpoints.length > 3 && (
                                  <span className="text-[10px] text-gray-400">+{cap.endpoints.length - 3}</span>
                                )}
                              </div>
                            </div>
                          </div>
                        </label>
                      );
                    })}
                  </div>
                )}
              </div>

              {/* Action buttons */}
              {saveError && (
                <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                  <XCircle size={16} className="mt-0.5 shrink-0" />
                  <span>{saveError}</span>
                </div>
              )}

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

