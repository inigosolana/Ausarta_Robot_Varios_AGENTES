import React, { useState, useEffect, useMemo } from 'react';
import {
  Building2, Eye, EyeOff, Loader2, CheckCircle2, XCircle, Copy, Check,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { apiFetch } from '../lib/apiFetch';
import { useAuth } from '../contexts/AuthContext';
import { useAdminEmpresasOptions } from '../api/apiKeys';
import {
  useTelephonyPlatformInfo,
  useYeastarCapabilities,
  useYeastarConfig,
  useYeastarHealth,
  useInvalidateTelephony,
  type YeastarConfig,
} from '../api/telephony';
import './telephony.css';

interface YeastarConfigForm extends YeastarConfig {}

const EMPTY_FORM: YeastarConfigForm = {
  yeastar_pbx_url: '',
  yeastar_api_mode: 'pseries',
  yeastar_client_id: '',
  yeastar_client_secret: '',
  enabled_capabilities: [],
  ddi: '',
};

const CAP_ICONS: Record<string, string> = {
  'extensions.read': 'contact_phone',
  'extensions.write': 'person_add',
  'calls.control': 'call_merge',
  'events.webhooks': 'troubleshoot',
  'trunks.read': 'settings_ethernet',
  'trunks.write': 'hub',
  'routes.read': 'route',
  'routes.write': 'alt_route',
  'contacts.manage': 'contacts',
  'queues.manage': 'groups',
  'cdr.recordings': 'mic',
  'system.read': 'dns',
};

function MaterialIcon({ name, className = '' }: { name: string; className?: string }) {
  return <span className={`material-symbols-outlined tel-icon ${className}`}>{name}</span>;
}

const formatApiError = (detail: unknown, fallback: string) => {
  if (!detail) return fallback;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item: { loc?: string[]; msg?: string; message?: string }) => {
        const path = Array.isArray(item?.loc) ? item.loc.join('.') : '';
        const msg = item?.msg || item?.message || JSON.stringify(item);
        return path ? `${path}: ${msg}` : msg;
      })
      .join(' | ');
  }
  if (typeof detail === 'object') {
    const data = detail as Record<string, string>;
    return data.message || data.msg || data.error || JSON.stringify(data);
  }
  return String(detail);
};

const TelephonyView: React.FC = () => {
  const { t } = useTranslation();
  const { profile, isPlatformOwner } = useAuth();
  const { invalidateConfig, invalidateHealth } = useInvalidateTelephony();

  const [form, setForm] = useState<YeastarConfigForm>(EMPTY_FORM);
  const [savedConfig, setSavedConfig] = useState<YeastarConfig | null>(null);
  const [showPassword, setShowPassword] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [autoConfigResult, setAutoConfigResult] = useState<{ sip_trunk?: unknown; inbound_route?: unknown; event_push?: unknown; errors?: string[] } | null>(null);
  const [healthRefreshing, setHealthRefreshing] = useState(false);

  const [selectedEmpresaId, setSelectedEmpresaId] = useState<number | null>(null);
  const [ausartaPublicIp, setAusartaPublicIp] = useState(
    () => (import.meta.env.VITE_AUSARTA_PUBLIC_IP as string | undefined)?.trim() || '',
  );
  const [yeastarWebhookUrl, setYeastarWebhookUrl] = useState('');
  const [webhookCopied, setWebhookCopied] = useState(false);
  const [ipCopied, setIpCopied] = useState(false);

  const { data: platformInfo } = useTelephonyPlatformInfo();
  const { data: capabilities = [], isLoading: capabilitiesLoading } = useYeastarCapabilities();
  const { data: empresasOptions = [] } = useAdminEmpresasOptions(isPlatformOwner);
  const {
    data: configData,
    isLoading: loadingConfig,
    isFetching: fetchingConfig,
  } = useYeastarConfig(selectedEmpresaId, Boolean(selectedEmpresaId));
  const {
    data: healthStatus = null,
    isLoading: healthLoading,
    isFetching: healthFetching,
  } = useYeastarHealth(selectedEmpresaId, Boolean(selectedEmpresaId));

  const isCloudMode = form.yeastar_api_mode === 'cloud_pbx';
  const currentModeLabel = isCloudMode ? 'Cloud PBX' : 'P-Series';
  const currentCredentialLabel = isCloudMode ? 'API Username' : 'Client ID';
  const currentSecretLabel = isCloudMode ? 'API Password' : 'Client Secret';
  const isConfigured = Boolean(savedConfig?.yeastar_pbx_url);

  const selectedEmpresaName = useMemo(() => {
    if (!selectedEmpresaId) return null;
    return empresasOptions.find(e => Number(e.id) === selectedEmpresaId)?.nombre
      ?? (profile?.empresa_id === selectedEmpresaId ? profile?.empresas?.nombre : null);
  }, [selectedEmpresaId, empresasOptions, profile]);

  useEffect(() => {
    const ip = String(platformInfo?.ausarta_public_ip || '').trim();
    if (ip) setAusartaPublicIp(ip);
    const webhook = String(platformInfo?.yeastar_webhook_url || '').trim();
    if (webhook) {
      setYeastarWebhookUrl(webhook);
    } else if (typeof window !== 'undefined') {
      setYeastarWebhookUrl(`${window.location.origin}/webhooks/yeastar`);
    }
  }, [platformInfo]);

  useEffect(() => {
    if (isPlatformOwner) {
      if (!empresasOptions.length) return;
      setSelectedEmpresaId(prev => {
        if (prev != null) return prev;
        const ausarta = empresasOptions.find(emp => emp.nombre?.toLowerCase() === 'ausarta');
        return ausarta?.id ?? empresasOptions[0]?.id ?? null;
      });
      return;
    }
    if (profile?.empresa_id) {
      setSelectedEmpresaId(profile.empresa_id);
    }
  }, [profile, isPlatformOwner, empresasOptions]);

  useEffect(() => {
    if (!selectedEmpresaId) {
      setForm(EMPTY_FORM);
      setSavedConfig(null);
      setTestResult(null);
      setSaveSuccess(false);
      return;
    }
    if (fetchingConfig) return;
    setTestResult(null);
    setSaveSuccess(false);
    if (!configData) {
      setSavedConfig(null);
      setForm(EMPTY_FORM);
      return;
    }
    setSavedConfig(configData);
    setForm({
      yeastar_pbx_url: configData.yeastar_pbx_url || '',
      yeastar_api_mode: configData.yeastar_api_mode || 'pseries',
      yeastar_client_id: configData.yeastar_client_id || '',
      yeastar_client_secret: '',
      enabled_capabilities: configData.enabled_capabilities || [],
      ddi: configData.ddi || '',
    });
  }, [selectedEmpresaId, configData, fetchingConfig]);

  const copyText = async (text: string, setter: (v: boolean) => void) => {
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setter(true);
      setTimeout(() => setter(false), 2000);
    } catch { /* ignore */ }
  };

  const forceHealthCheck = async () => {
    if (!selectedEmpresaId) return;
    setHealthRefreshing(true);
    try {
      const res = await apiFetch(`/api/empresas/${selectedEmpresaId}/yeastar/health/check`, {
        method: 'POST',
      });
      if (res.ok) {
        await invalidateHealth(selectedEmpresaId);
      }
    } catch {
      /* ignore */
    } finally {
      setHealthRefreshing(false);
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
    } catch {
      setTestResult({ ok: false, message: t('Connection error', 'Error de conexión con el servidor') });
    } finally {
      setTesting(false);
    }
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.yeastar_pbx_url || !form.yeastar_client_id || !selectedEmpresaId) return;
    setSaving(true);
    setSaveSuccess(false);
    setSaveError('');
    try {
      const payload: Record<string, unknown> = {
        empresa_id: selectedEmpresaId,
        yeastar_pbx_url: form.yeastar_pbx_url,
        yeastar_api_mode: form.yeastar_api_mode,
        yeastar_client_id: form.yeastar_client_id,
        enabled_capabilities: form.enabled_capabilities || [],
      };
      if (form.ddi?.trim()) {
        payload.ddi = form.ddi.trim();
      }
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
      const saved: YeastarConfig & { auto_config_result?: { sip_trunk?: unknown; inbound_route?: unknown; event_push?: unknown; errors?: string[] } } = await res.json();
      setSavedConfig(saved);
      setAutoConfigResult(saved.auto_config_result || null);
      setForm(prev => ({
        ...prev,
        yeastar_client_secret: '',
        enabled_capabilities: saved.enabled_capabilities || [],
        ddi: saved.ddi || prev.ddi || '',
      }));
      setSaveSuccess(true);
      if (selectedEmpresaId) {
        await invalidateConfig(selectedEmpresaId);
      }
      setTimeout(() => { setSaveSuccess(false); setAutoConfigResult(null); }, 8000);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : t('Save error', 'Error al guardar la configuracion'));
    } finally {
      setSaving(false);
    }
  };

  const statusLabel = (loadingConfig || fetchingConfig)
    ? 'SINCRONIZANDO'
    : isConfigured
      ? 'ENLACE ACTIVO'
      : 'SIN CONFIGURAR';

  const yeastarHealth = healthStatus?.health_status || 'unknown';
  const healthDotClass =
    yeastarHealth === 'ok'
      ? 'bg-emerald-500'
      : yeastarHealth === 'down'
        ? 'bg-red-500'
        : 'bg-gray-400';
  const healthLabel =
    yeastarHealth === 'ok'
      ? t('PBX OK', 'PBX operativo')
      : yeastarHealth === 'down'
        ? t('PBX DOWN', 'PBX sin respuesta')
        : t('PBX unknown', 'PBX sin comprobar');
  const campaignsPausedByHealth = (healthStatus?.campaigns_paused_count ?? 0) > 0;

  return (
    <div className="telephony-page relative min-h-full">
      <div className="pointer-events-none absolute top-0 right-1/4 h-[420px] w-[420px] rounded-full bg-cyan-500/10 blur-[120px]" />
      <div className="pointer-events-none absolute top-1/4 right-0 h-[360px] w-[360px] rounded-full bg-indigo-500/10 blur-[150px]" />

      <div className="relative z-10 mx-auto max-w-7xl space-y-6">
        {/* Empresa bar */}
        <div className="tel-empresa-bar flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-indigo-500/15 text-indigo-600 dark:text-indigo-300">
              <Building2 size={22} />
            </div>
            <div>
              <p className="tel-mono text-xs font-bold uppercase tracking-widest text-indigo-600/80 dark:text-indigo-300/90">
                {t('Company to configure', 'Empresa a configurar')}
              </p>
              <p className="text-sm font-semibold text-gray-900 dark:text-white">
                {selectedEmpresaName || (isPlatformOwner ? 'Selecciona una empresa' : 'Tu empresa')}
              </p>
            </div>
          </div>
          {isPlatformOwner && (
            <select
              value={selectedEmpresaId || ''}
              onChange={e => setSelectedEmpresaId(e.target.value ? Number(e.target.value) : null)}
              className="tel-field min-w-[220px] px-3 py-2.5 font-medium"
            >
              <option value="">{t('Select a company', 'Selecciona una empresa')}</option>
              {empresasOptions.map(emp => (
                <option key={emp.id} value={emp.id}>{emp.nombre}</option>
              ))}
            </select>
          )}
        </div>

        {/* Header */}
        <header className="flex flex-col gap-4 border-b border-gray-200 pb-6 dark:border-white/10 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div className="mb-2 flex items-center gap-2">
              {isConfigured && !(loadingConfig || fetchingConfig) ? (
                <span className="relative flex h-2.5 w-2.5">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
                  <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-500" />
                </span>
              ) : (
                <span className="h-2.5 w-2.5 rounded-full bg-gray-300 dark:bg-gray-600" />
              )}
              <span className={`tel-mono text-xs font-bold uppercase tracking-wider ${
                isConfigured ? 'text-emerald-600 dark:text-emerald-400' : 'text-gray-400'
              }`}>
                {statusLabel}
              </span>
            </div>
            <h1 className="text-3xl font-bold tracking-tight text-gray-900 dark:text-white">
              PBX Yeastar API
            </h1>
            <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
              {t(
                'Configure your telephony provider for outbound calls and transfers.',
                'Consola de integración para Yeastar P-Series y Cloud — llamadas, transferencias y webhooks.',
              )}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {isConfigured && selectedEmpresaId && (
              <span
                className="tel-glass flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-semibold"
                title={
                  healthStatus?.last_health_check_at
                    ? `${t('Last check', 'Última comprobación')}: ${healthStatus.last_health_check_at}`
                    : undefined
                }
              >
                <span className={`h-2 w-2 rounded-full ${healthDotClass} ${yeastarHealth === 'down' ? 'animate-pulse' : ''}`} />
                <span className={
                  yeastarHealth === 'ok'
                    ? 'text-emerald-700 dark:text-emerald-400'
                    : yeastarHealth === 'down'
                      ? 'text-red-700 dark:text-red-400'
                      : 'text-gray-500'
                }>
                  {healthLoading || healthFetching || healthRefreshing ? t('Checking...', 'Comprobando...') : healthLabel}
                </span>
              </span>
            )}
            <span className="tel-glass rounded-full px-3 py-1.5 text-xs font-semibold text-indigo-700 dark:text-indigo-300">
              {currentModeLabel}
            </span>
            {selectedEmpresaId && (
              <>
                <button
                  type="button"
                  onClick={forceHealthCheck}
                  disabled={healthRefreshing}
                  className="tel-glass rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs font-medium text-gray-600 transition-colors hover:text-cyan-600 disabled:opacity-50 dark:border-white/10 dark:text-gray-300 dark:hover:text-cyan-400"
                  title={t('Force health check', 'Forzar comprobación de salud')}
                >
                  {healthRefreshing ? (
                    <Loader2 size={16} className="animate-spin" />
                  ) : (
                    <MaterialIcon name="monitor_heart" className="!text-base" />
                  )}
                </button>
                <button
                  type="button"
                  onClick={() => { loadConfig(selectedEmpresaId); loadHealth(selectedEmpresaId); }}
                  className="tel-glass rounded-lg border border-gray-200 p-2 text-gray-500 transition-colors hover:text-cyan-600 dark:border-white/10 dark:hover:text-cyan-400"
                  title="Recargar"
                >
                  <MaterialIcon name="sync" className="!text-xl" />
                </button>
              </>
            )}
          </div>
        </header>

        {campaignsPausedByHealth && selectedEmpresaId && (
          <div className="rounded-xl border border-amber-300/60 bg-amber-50/90 px-4 py-3 text-sm text-amber-900 dark:border-amber-700/50 dark:bg-amber-950/40 dark:text-amber-100">
            <p className="font-semibold">
              {t(
                'Campaigns paused — Yeastar unreachable',
                'Campañas pausadas — Yeastar sin respuesta',
              )}
            </p>
            <p className="mt-1 text-amber-800/90 dark:text-amber-200/90">
              {t(
                'The PBX health check failed repeatedly. Outbound campaigns were paused automatically and will resume when Yeastar responds again.',
                'El health-check del PBX falló varias veces. Las campañas salientes se pausaron automáticamente y se reanudarán cuando Yeastar vuelva a responder.',
              )}
            </p>
            {healthStatus?.campaigns_paused_by_health && healthStatus.campaigns_paused_by_health.length > 0 && (
              <ul className="mt-2 list-inside list-disc text-xs">
                {healthStatus.campaigns_paused_by_health.map(c => (
                  <li key={c.id}>{c.name || `Campaña #${c.id}`}</li>
                ))}
              </ul>
            )}
          </div>
        )}

        {!selectedEmpresaId ? (
          <div className="tel-glass rounded-2xl p-12 text-center text-gray-500 dark:text-gray-400">
            {t('Select a company to configure telephony.', 'Selecciona una empresa para configurar la telefonía.')}
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
            {/* Left column */}
            <div className="space-y-6 lg:col-span-7">
              {/* Credentials */}
              <section className="tel-glass tel-glass-glow relative overflow-hidden rounded-xl p-6">
                <div className="mb-6 flex items-center gap-3">
                  <MaterialIcon name="admin_panel_settings" className="text-indigo-600 dark:text-indigo-300" />
                  <h2 className="tel-mono text-sm font-bold uppercase tracking-widest text-gray-900 dark:text-white">
                    Consola de credenciales
                  </h2>
                </div>

                {(loadingConfig || fetchingConfig) ? (
                  <div className="flex items-center justify-center gap-3 py-16 text-gray-400">
                    <Loader2 size={22} className="animate-spin" />
                    <span className="text-sm">{t('Loading configuration...', 'Cargando configuración...')}</span>
                  </div>
                ) : (
                  <form onSubmit={handleSave} className="space-y-4">
                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                      <div>
                        <label className="mb-1.5 block text-xs font-medium text-gray-500 dark:text-gray-400">
                          {t('PBX URL', 'URL de la centralita')} *
                        </label>
                        <input
                          type="url"
                          required
                          value={form.yeastar_pbx_url}
                          onChange={e => handleChange('yeastar_pbx_url', e.target.value)}
                          placeholder={isCloudMode ? 'https://pbx.empresa.cloud:443' : 'https://pbx.empresa.com:8088'}
                          className="tel-field tel-mono px-3 py-2.5"
                        />
                      </div>
                      <div>
                        <label className="mb-1.5 block text-xs font-medium text-gray-500 dark:text-gray-400">
                          {t('API Mode', 'Modo de API')} *
                        </label>
                        <select
                          value={form.yeastar_api_mode}
                          onChange={e => handleChange('yeastar_api_mode', e.target.value)}
                          className="tel-field px-3 py-2.5"
                        >
                          <option value="pseries">Yeastar P-Series OpenAPI</option>
                          <option value="cloud_pbx">Yeastar Cloud PBX legacy</option>
                        </select>
                      </div>
                    </div>

                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                      <div>
                        <label className="mb-1.5 block text-xs font-medium text-gray-500 dark:text-gray-400">
                          {currentCredentialLabel} *
                        </label>
                        <input
                          type="text"
                          required
                          autoComplete="off"
                          value={form.yeastar_client_id}
                          onChange={e => handleChange('yeastar_client_id', e.target.value)}
                          className="tel-field tel-mono px-3 py-2.5"
                        />
                      </div>
                      <div>
                        <label className="mb-1.5 block text-xs font-medium text-gray-500 dark:text-gray-400">
                          {currentSecretLabel}
                          {savedConfig?.yeastar_pbx_url && (
                            <span className="ml-1 font-normal text-gray-400">
                              ({t('leave blank to keep current', 'vacío = conservar')})
                            </span>
                          )}
                        </label>
                        <div className="relative">
                          <input
                            type={showPassword ? 'text' : 'password'}
                            autoComplete="new-password"
                            value={form.yeastar_client_secret}
                            onChange={e => handleChange('yeastar_client_secret', e.target.value)}
                            placeholder={savedConfig?.yeastar_pbx_url ? '********' : ''}
                            required={!savedConfig?.yeastar_pbx_url}
                            className="tel-field tel-mono w-full px-3 py-2.5 pr-10"
                          />
                          <button
                            type="button"
                            onClick={() => setShowPassword(v => !v)}
                            className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
                          >
                            {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                          </button>
                        </div>
                      </div>
                    </div>

                    {/* DDI — número entrante del cliente */}
                    <div className="rounded-xl border border-indigo-100 bg-indigo-50/60 p-4 dark:border-indigo-900/30 dark:bg-indigo-950/20">
                      <div className="mb-3 flex items-center gap-2">
                        <MaterialIcon name="call_received" className="!text-lg text-indigo-600 dark:text-indigo-400" />
                        <div>
                          <p className="text-sm font-semibold text-gray-900 dark:text-white">
                            DDI / Número entrante del cliente
                          </p>
                          <p className="text-xs text-gray-500 dark:text-gray-400">
                            Al guardar, se creará automáticamente la ruta entrante en Yeastar y se configurará el Event Push.
                          </p>
                        </div>
                      </div>
                      <input
                        type="tel"
                        value={form.ddi || ''}
                        onChange={e => handleChange('ddi', e.target.value)}
                        placeholder="+34911234501"
                        className="tel-field tel-mono px-3 py-2.5"
                      />
                      <p className="mt-1.5 text-[11px] text-indigo-600/70 dark:text-indigo-400/70">
                        Formato E.164 recomendado. Opcional — si no se rellena, la ruta y el webhook se configuran manualmente.
                      </p>
                    </div>

                    {testResult && (
                      <div className={`flex items-start gap-2 rounded-lg border px-3 py-2.5 text-sm ${
                        testResult.ok
                          ? 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900/40 dark:bg-emerald-950/30 dark:text-emerald-300'
                          : 'border-red-200 bg-red-50 text-red-700 dark:border-red-900/40 dark:bg-red-950/30 dark:text-red-300'
                      }`}>
                        {testResult.ok ? <CheckCircle2 size={16} className="shrink-0 mt-0.5" /> : <XCircle size={16} className="shrink-0 mt-0.5" />}
                        <span>{testResult.message}</span>
                      </div>
                    )}

                    {saveSuccess && (
                      <div className="space-y-2">
                        <div className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2.5 text-sm text-emerald-800 dark:border-emerald-900/40 dark:bg-emerald-950/30 dark:text-emerald-300">
                          <CheckCircle2 size={16} />
                          {t('Configuration saved successfully.', 'Configuración guardada correctamente.')}
                        </div>
                        {autoConfigResult && (
                          <div className={`rounded-lg border px-3 py-2.5 text-xs ${
                            (autoConfigResult.errors?.length ?? 0) === 0
                              ? 'border-indigo-200 bg-indigo-50 text-indigo-800 dark:border-indigo-900/40 dark:bg-indigo-950/30 dark:text-indigo-300'
                              : 'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900/40 dark:bg-amber-950/30 dark:text-amber-300'
                          }`}>
                            <p className="mb-1 font-semibold">Autoconfiguración Yeastar:</p>
                            <p>• Troncal SIP LiveKit: {autoConfigResult.sip_trunk ? (autoConfigResult.sip_trunk as Record<string, unknown>)?.skipped ? 'omitida (cloud_pbx)' : (autoConfigResult.sip_trunk as Record<string, unknown>)?.reused ? '✅ ya existía' : '✅ creada' : '—'}</p>
                            <p>• Ruta entrante: {autoConfigResult.inbound_route ? (autoConfigResult.inbound_route as Record<string, unknown>)?.skipped ? 'omitida (cloud_pbx)' : '✅ creada' : '—'}</p>
                            <p>• Event Push: {autoConfigResult.event_push ? (autoConfigResult.event_push as Record<string, unknown>)?.skipped ? 'omitido (cloud_pbx)' : '✅ configurado' : '—'}</p>
                            {(autoConfigResult.errors?.length ?? 0) > 0 && (
                              <ul className="mt-1 list-inside list-disc space-y-0.5 text-amber-700 dark:text-amber-400">
                                {autoConfigResult.errors!.map((e, i) => <li key={i}>{e}</li>)}
                              </ul>
                            )}
                          </div>
                        )}
                      </div>
                    )}

                    {saveError && (
                      <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2.5 text-sm text-red-700 dark:border-red-900/40 dark:bg-red-950/30 dark:text-red-300">
                        <XCircle size={16} className="shrink-0 mt-0.5" />
                        <span>{saveError}</span>
                      </div>
                    )}

                    <div className="flex flex-wrap justify-end gap-3 border-t border-gray-100 pt-4 dark:border-white/10">
                      <button
                        type="button"
                        onClick={handleTest}
                        disabled={testing || !form.yeastar_pbx_url || !form.yeastar_client_id}
                        className="inline-flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-5 py-2.5 text-sm font-semibold text-gray-700 transition-colors hover:bg-gray-50 disabled:opacity-40 dark:border-white/10 dark:bg-gray-900/50 dark:text-gray-200 dark:hover:bg-gray-800"
                      >
                        {testing ? <Loader2 size={16} className="animate-spin" /> : <MaterialIcon name="network_ping" className="!text-lg" />}
                        {testing ? t('Testing...', 'Probando...') : t('Test Connection', 'Probar conexión')}
                      </button>
                      <button
                        type="submit"
                        disabled={saving || !form.yeastar_pbx_url || !form.yeastar_client_id}
                        className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-6 py-2.5 text-sm font-bold text-white shadow-lg shadow-indigo-500/20 transition-colors hover:bg-indigo-500 disabled:opacity-40 dark:bg-indigo-500 dark:hover:bg-indigo-400"
                      >
                        {saving ? <Loader2 size={16} className="animate-spin" /> : <MaterialIcon name="save" className="!text-lg" />}
                        {saving ? t('Saving...', 'Guardando...') : t('Save Configuration', 'Guardar configuración')}
                      </button>
                    </div>
                  </form>
                )}
              </section>

              {/* Technical briefing */}
              <section className="tel-glass rounded-xl p-6">
                <div className="mb-6 flex items-center gap-3 border-b border-gray-100 pb-4 dark:border-white/10">
                  <MaterialIcon name="integration_instructions" className="text-cyan-600 dark:text-cyan-400" />
                  <h2 className="tel-mono text-sm font-bold uppercase tracking-widest text-gray-900 dark:text-white">
                    Guía técnica
                  </h2>
                </div>

                <div className="relative space-y-8 before:absolute before:inset-y-0 before:left-[15px] before:w-0.5 before:bg-gray-200 dark:before:bg-white/10">
                  {/* Step 1 */}
                  <div className="relative pl-10">
                    <div className="absolute left-0 top-1 z-10 flex h-8 w-8 items-center justify-center rounded-full border border-cyan-400 bg-white text-sm font-bold text-cyan-600 shadow-sm dark:border-cyan-500/50 dark:bg-gray-900 dark:text-cyan-400">
                      1
                    </div>
                    <h3 className="font-semibold text-gray-900 dark:text-white">Crear conexión API</h3>
                    <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                      En Yeastar: <strong>Integraciones → API</strong>. Permisos mínimos:
                    </p>
                    <div className="tel-mono mt-3 rounded-lg border border-gray-200 bg-gray-50 p-3 text-xs text-gray-600 dark:border-white/10 dark:bg-gray-900/50 dark:text-gray-300">
                      <p>• <span className="text-cyan-600 dark:text-cyan-400">Extension GET</span> — consultar si la extensión está libre</p>
                      <p>• <span className="text-cyan-600 dark:text-cyan-400">Call Control POST</span> — ejecutar transferencias</p>
                    </div>
                  </div>

                  {/* Step 2 */}
                  <div className="relative pl-10">
                    <div className="absolute left-0 top-1 z-10 flex h-8 w-8 items-center justify-center rounded-full border border-gray-300 bg-white text-sm font-bold text-gray-500 dark:border-white/20 dark:bg-gray-900 dark:text-gray-400">
                      2
                    </div>
                    <h3 className="font-semibold text-gray-900 dark:text-white">IP permitida</h3>
                    <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                      Añade la IP pública de Ausarta en la whitelist de Yeastar. Máscara: <code className="tel-mono">255.255.255.255</code>
                    </p>
                    <div className="mt-3 flex items-center justify-between rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 dark:border-white/10 dark:bg-gray-900/50">
                      <code className="tel-mono text-sm text-indigo-600 dark:text-indigo-300">
                        {ausartaPublicIp || '[AUSARTA_PUBLIC_IP en .env del backend]'}
                      </code>
                      {ausartaPublicIp && (
                        <button
                          type="button"
                          onClick={() => copyText(ausartaPublicIp, setIpCopied)}
                          className="text-gray-400 hover:text-indigo-600 dark:hover:text-indigo-300"
                        >
                          {ipCopied ? <Check size={14} /> : <Copy size={14} />}
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Step 3 */}
                  <div className="relative pl-10">
                    <div className="absolute left-0 top-1 z-10 flex h-8 w-8 items-center justify-center rounded-full border border-gray-300 bg-white text-sm font-bold text-gray-500 dark:border-white/20 dark:bg-gray-900 dark:text-gray-400">
                      3
                    </div>
                    <h3 className="font-semibold text-gray-900 dark:text-white">Webhook (evento 30011)</h3>
                    <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                      En <strong>Integraciones → Webhook</strong>. Evento obligatorio: <strong>30011 — Call State Changed</strong>
                    </p>
                    <div className="mt-3 space-y-2 rounded-lg border border-gray-200 bg-gray-50 p-3 dark:border-white/10 dark:bg-gray-900/50">
                      <div className="flex items-center justify-between gap-2">
                        <code className="tel-mono break-all text-xs text-gray-600 dark:text-gray-300">
                          {yeastarWebhookUrl || 'https://tu-dominio/webhooks/yeastar'}
                        </code>
                        {yeastarWebhookUrl && (
                          <button
                            type="button"
                            onClick={() => copyText(yeastarWebhookUrl, setWebhookCopied)}
                            className="shrink-0 text-gray-400 hover:text-indigo-600 dark:hover:text-indigo-300"
                          >
                            {webhookCopied ? <Check size={14} /> : <Copy size={14} />}
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              </section>
            </div>

            {/* Right column */}
            <div className="space-y-6 lg:col-span-5">
              {/* Capability matrix */}
              <section className="tel-glass tel-glass-cyan rounded-xl p-6">
                <div className="mb-4 flex items-center justify-between border-b border-gray-100 pb-4 dark:border-white/10">
                  <div className="flex items-center gap-3">
                    <MaterialIcon name="memory" className="text-cyan-600 dark:text-cyan-400" />
                    <h2 className="tel-mono text-sm font-bold uppercase tracking-widest text-gray-900 dark:text-white">
                      Matriz de capacidades
                    </h2>
                  </div>
                  <span className="rounded-md border border-cyan-200 bg-cyan-50 px-2 py-1 text-[10px] font-bold text-cyan-700 dark:border-cyan-500/30 dark:bg-cyan-950/30 dark:text-cyan-300">
                    {(form.enabled_capabilities || []).length} activas
                  </span>
                </div>

                {capabilitiesLoading ? (
                  <div className="flex items-center gap-2 py-8 text-sm text-gray-400">
                    <Loader2 size={16} className="animate-spin" />
                    Cargando capacidades…
                  </div>
                ) : (
                  <div className="max-h-[520px] space-y-3 overflow-y-auto pr-1">
                    {capabilities.map(cap => {
                      const active = (form.enabled_capabilities || []).includes(cap.id);
                      const icon = CAP_ICONS[cap.id] || 'api';
                      const endpoint = cap.endpoints[0] || cap.permission;
                      const statusCls = cap.status === 'implemented'
                        ? 'text-emerald-600 dark:text-emerald-400'
                        : cap.status === 'planned'
                          ? 'text-amber-600 dark:text-amber-400'
                          : 'text-gray-500 dark:text-gray-400';
                      return (
                        <label
                          key={cap.id}
                          className={`tel-cap-card flex cursor-pointer gap-3 rounded-lg p-4 ${active ? 'tel-cap-card--active' : ''}`}
                        >
                          <input
                            type="checkbox"
                            checked={active}
                            onChange={() => toggleCapability(cap.id)}
                            className="mt-1 h-4 w-4 shrink-0 rounded border-gray-300 text-cyan-600 focus:ring-cyan-500"
                          />
                          <div className="flex min-w-0 flex-1 gap-3">
                            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-gray-200 bg-white dark:border-white/10 dark:bg-gray-900">
                              <MaterialIcon name={icon} className="!text-lg text-indigo-600 dark:text-indigo-300" />
                            </div>
                            <div className="min-w-0 flex-1">
                              <div className="flex flex-wrap items-center justify-between gap-1">
                                <span className="text-sm font-semibold text-gray-900 dark:text-white">{cap.label}</span>
                                <span className={`tel-mono text-[10px] font-medium ${statusCls}`}>
                                  {cap.status === 'implemented' ? 'listo' : cap.status === 'planned' ? 'plan' : 'disp.'}
                                </span>
                              </div>
                              <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">{cap.description}</p>
                              <code className="tel-mono mt-1.5 inline-block rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-600 dark:bg-gray-900 dark:text-gray-400">
                                {endpoint}
                              </code>
                            </div>
                          </div>
                        </label>
                      );
                    })}
                  </div>
                )}
              </section>

              {/* Hazard zone */}
              <section className="tel-glass tel-glass-danger rounded-xl border border-red-200/80 p-6 dark:border-red-900/40">
                <div className="mb-4 flex items-center gap-3">
                  <MaterialIcon name="warning" className="text-red-500" />
                  <h2 className="tel-mono text-sm font-bold uppercase tracking-widest text-red-600 dark:text-red-400">
                    Zona de riesgo
                  </h2>
                </div>
                <div className="rounded-lg border border-red-100 bg-red-50/50 p-4 dark:border-red-900/30 dark:bg-red-950/20">
                  <h3 className="text-sm font-semibold text-gray-900 dark:text-white">
                    {t('Reset Rooms and Unlock System', 'Resetear salas y desbloquear')}
                  </h3>
                  <p className="mt-1 text-xs text-gray-600 dark:text-gray-400">
                    {t(
                      'If the system hangs with the message "Calls in progress" and the agent does not respond, you can force the cleanup of all active rooms.',
                      'Si el sistema se queda bloqueado con "Hay llamadas en curso", fuerza la limpieza de todas las salas activas. Colgará las llamadas en curso.',
                    )}
                  </p>
                  <button
                    type="button"
                    onClick={async () => {
                      if (!window.confirm(t(
                        'Are you sure you want to force close ALL active calls?',
                        '¿Forzar el cierre de TODAS las llamadas activas?',
                      ))) return;
                      try {
                        const res = await fetch(`${(import.meta.env.VITE_API_URL as string) || '/api'}/calls/cleanup`, { method: 'POST' });
                        if (res.ok) alert(t('✅ System cleaned successfully.', '✅ Sistema limpiado correctamente.'));
                        else alert(t('❌ Error cleaning the rooms.', '❌ Error al limpiar las salas.'));
                      } catch {
                        alert(t('Server connection error.', 'Error de conexión con el servidor.'));
                      }
                    }}
                    className="mt-4 flex w-full items-center justify-center gap-2 rounded-lg border border-red-300 bg-red-100/80 py-2.5 text-sm font-bold text-red-700 transition-colors hover:bg-red-200/80 dark:border-red-800 dark:bg-red-950/40 dark:text-red-300 dark:hover:bg-red-950/60"
                  >
                    <MaterialIcon name="delete_forever" className="!text-lg" />
                    {t('Extreme Cleanup', 'Limpieza extrema')}
                  </button>
                </div>
              </section>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default TelephonyView;
