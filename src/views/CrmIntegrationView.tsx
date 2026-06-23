import React, { useEffect, useState } from 'react';
import {
    Building2,
    CheckCircle2,
    Database,
    ExternalLink,
    Link as LinkIcon,
    Save,
    Webhook,
    Zap,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import toast from 'react-hot-toast';
import { apiFetch } from '../lib/apiFetch';
import { useAuth } from '../contexts/AuthContext';
import { useEmpresasAdmin } from '../api/empresas';
import { useCrmConfig, useInvalidateCrmConfig } from '../api/crm';

const ZAPIER_TEST_PAYLOAD = {
    event: 'call.completed',
    call_id: 9999,
    phone: '+34600000000',
    status: 'completed',
    date: new Date().toISOString(),
    campaign_name: 'Campana de Prueba',
    transcription: 'Hola, prueba de integracion Zapier/Make exitosa.',
    datos_extra: {
        interesado: true,
        nota_satisfaccion: 8,
        motivo: 'Precio muy competitivo',
    },
    interesado: true,
    nota_satisfaccion: 8,
    motivo: 'Precio muy competitivo',
};

type CrmOption = {
    id: string;
    name: string;
    subtitle: string;
    logoUrl: string;
    docsUrl: string;
    accent: string;
};

const CRM_OPTIONS: CrmOption[] = [
    {
        id: 'hubspot',
        name: 'HubSpot',
        subtitle: 'Contacts, deals y activity timeline',
        logoUrl: 'https://cdn.simpleicons.org/hubspot/ff7a59',
        docsUrl: 'https://developers.hubspot.com/docs/api/overview',
        accent: 'from-orange-50 to-amber-50 border-orange-200',
    },
    {
        id: 'salesforce',
        name: 'Salesforce',
        subtitle: 'Leads, tasks y actividad comercial',
        logoUrl: 'https://cdn.simpleicons.org/salesforce/00a1e0',
        docsUrl: 'https://developer.salesforce.com/docs/apis',
        accent: 'from-sky-50 to-cyan-50 border-sky-200',
    },
    {
        id: 'pipedrive',
        name: 'Pipedrive',
        subtitle: 'Persons, deals y activities',
        logoUrl: 'https://cdn.simpleicons.org/pipedrive/139e4a',
        docsUrl: 'https://developers.pipedrive.com/docs/api/v1',
        accent: 'from-emerald-50 to-lime-50 border-emerald-200',
    },
    {
        id: 'zohocrm',
        name: 'Zoho CRM',
        subtitle: 'Modulos CRM y workflows',
        logoUrl: 'https://cdn.simpleicons.org/zohocrm/d81b60',
        docsUrl: 'https://www.zoho.com/crm/developer/docs/api/v8/overview.html',
        accent: 'from-rose-50 to-pink-50 border-rose-200',
    },
    {
        id: 'dynamics365',
        name: 'Dynamics 365',
        subtitle: 'Dataverse, leads y opportunities',
        logoUrl: 'https://cdn.simpleicons.org/microsoftdynamics365/0b53ce',
        docsUrl: 'https://learn.microsoft.com/en-us/power-apps/developer/data-platform/webapi/overview',
        accent: 'from-blue-50 to-indigo-50 border-blue-200',
    },
    {
        id: 'freshsales',
        name: 'Freshsales',
        subtitle: 'Contacts y deals para ventas',
        logoUrl: 'https://cdn.simpleicons.org/freshworks/1d9bd1',
        docsUrl: 'https://developers.freshworks.com/crm/api/',
        accent: 'from-cyan-50 to-teal-50 border-cyan-200',
    },
    {
        id: 'custom',
        name: 'Webhook propio',
        subtitle: 'n8n, middleware o CRM generico',
        logoUrl: 'https://cdn.simpleicons.org/webhooks/4f46e5',
        docsUrl: 'https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook/',
        accent: 'from-slate-50 to-gray-50 border-slate-200',
    },
];

const CrmCard: React.FC<{
    option: CrmOption;
    selected: boolean;
    onSelect: (id: string) => void;
}> = ({ option, selected, onSelect }) => {
    return (
        <button
            type="button"
            onClick={() => onSelect(option.id)}
            className={`rounded-2xl border bg-gradient-to-br p-4 text-left transition-all ${option.accent} ${
                selected ? 'border-blue-400 ring-2 ring-blue-500 shadow-md' : 'hover:border-gray-300'
            }`}
        >
            <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-3 min-w-0">
                    <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-white/80 bg-white shadow-sm">
                        <img src={option.logoUrl} alt={option.name} className="h-6 w-6 object-contain" />
                    </div>
                    <div className="min-w-0">
                        <div className="font-semibold text-gray-900">{option.name}</div>
                        <div className="mt-1 text-xs text-gray-600">{option.subtitle}</div>
                    </div>
                </div>
                <a
                    href={option.docsUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={(e) => e.stopPropagation()}
                    className="text-gray-500 transition-colors hover:text-blue-600"
                    title="Open API docs"
                >
                    <ExternalLink size={14} />
                </a>
            </div>
        </button>
    );
};

const CrmIntegrationView: React.FC = () => {
    const { profile, isPlatformOwner } = useAuth();
    const { t } = useTranslation();
    const invalidateCrmConfig = useInvalidateCrmConfig();

    const { data: empresas = [], isLoading: empresasLoading } = useEmpresasAdmin(undefined, isPlatformOwner);
    const [selectedEmpresaId, setSelectedEmpresaId] = useState<number | null>(null);
    const [webhookUrl, setWebhookUrl] = useState('');
    const [crmType, setCrmType] = useState('hubspot');
    const [automationWebhookUrl, setAutomationWebhookUrl] = useState('');
    const [isSavingCrm, setIsSavingCrm] = useState(false);
    const [isSavingAutomation, setIsSavingAutomation] = useState(false);

    const {
        data: crmConfig,
        isLoading: configLoading,
        isFetching: configFetching,
    } = useCrmConfig(selectedEmpresaId, Boolean(selectedEmpresaId));
    const isLoading = empresasLoading || configLoading || configFetching;

    useEffect(() => {
        if (isPlatformOwner) {
            if (!empresas.length) return;
            setSelectedEmpresaId((prev) => {
                if (prev != null) return prev;
                const ausarta = empresas.find((emp) => emp.nombre?.toLowerCase() === 'ausarta');
                return ausarta?.id ?? empresas[0].id ?? null;
            });
            return;
        }
        if (profile?.empresa_id) {
            setSelectedEmpresaId(profile.empresa_id);
        }
    }, [profile?.empresa_id, isPlatformOwner, empresas]);

    useEffect(() => {
        if (!crmConfig) return;
        setCrmType(crmConfig.crm_type || 'hubspot');
        setWebhookUrl(crmConfig.crm_webhook_url || '');
        setAutomationWebhookUrl(crmConfig.webhook_url || '');
    }, [crmConfig, selectedEmpresaId]);

    const handleSaveCrm = async () => {
        if (!selectedEmpresaId) return;
        setIsSavingCrm(true);
        try {
            const res = await apiFetch(`/api/admin/empresas/${selectedEmpresaId}/crm-config`, {
                method: 'PUT',
                body: JSON.stringify({ crm_type: crmType, crm_webhook_url: webhookUrl }),
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            toast.success(t('CRM configuration saved', 'Configuracion CRM guardada'));
            if (selectedEmpresaId) invalidateCrmConfig(selectedEmpresaId);
        } catch (error) {
            console.error('Error saving CRM config:', error);
            toast.error(t('Error saving CRM config', 'Error al guardar configuracion CRM'));
        } finally {
            setIsSavingCrm(false);
        }
    };

    const handleSaveAutomation = async () => {
        if (!selectedEmpresaId) return;
        setIsSavingAutomation(true);
        try {
            const res = await apiFetch(`/api/admin/empresas/${selectedEmpresaId}/crm-config`, {
                method: 'PUT',
                body: JSON.stringify({ webhook_url: automationWebhookUrl || null }),
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            toast.success(t('Automation webhook saved', 'Webhook de automatizacion guardado'));
            if (selectedEmpresaId) invalidateCrmConfig(selectedEmpresaId);
        } catch (error) {
            console.error('Error saving automation webhook:', error);
            toast.error(t('Error saving webhook', 'Error al guardar webhook'));
        } finally {
            setIsSavingAutomation(false);
        }
    };

    const handleTestCrm = () => {
        if (!webhookUrl) return;
        toast.promise(
            fetch(webhookUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    test: true,
                    event: 'call_completed',
                    lead: { phone: '+34123456789', name: 'Test User' },
                    scores: { comercial: 8, instalador: 9, rapidez: 10 },
                    transcription: 'Hola, prueba de integracion CRM exitosa.',
                    crm_type: crmType,
                }),
            }).then((res) => {
                if (!res.ok) throw new Error();
            }),
            {
                loading: t('Sending test to CRM...', 'Enviando prueba al CRM...'),
                success: t('CRM webhook responded correctly', 'El webhook CRM respondio correctamente'),
                error: t('Webhook rejected the request', 'El webhook rechazo la peticion'),
            },
        );
    };

    const handleTestAutomation = () => {
        if (!automationWebhookUrl) return;
        toast.promise(
            fetch(automationWebhookUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(ZAPIER_TEST_PAYLOAD),
            }).then((res) => {
                if (!res.ok) throw new Error();
            }),
            {
                loading: t('Sending test to Zapier/Make...', 'Enviando prueba a Zapier/Make...'),
                success: t('Zapier/Make webhook responded correctly', 'El webhook respondio correctamente'),
                error: t('Webhook rejected the request', 'El webhook rechazo la peticion'),
            },
        );
    };

    if (isLoading) {
        return <div className="p-8 text-center text-gray-500">{t('Loading configuration...', 'Cargando configuración...')}</div>;
    }

    return (
        <div className="max-w-5xl space-y-8 animate-fade-in">
            <div>
                <h2 className="flex items-center gap-2 text-2xl font-bold text-gray-900">
                    <Database size={24} className="text-blue-500" />
                    {t('Integrations & Webhooks', 'Integraciones y Webhooks')}
                </h2>
                <p className="mt-1 text-gray-500">
                    {t(
                        'Connect call results to your CRM or automation tools automatically after each call.',
                        'Conecta los resultados de las llamadas a tu CRM o herramientas de automatización automáticamente tras cada llamada.',
                    )}
                </p>
            </div>

            {isPlatformOwner && (
                <div className="rounded-2xl border border-gray-100 bg-white p-5 shadow-sm">
                    <label className="mb-2 flex items-center gap-2 text-sm font-medium text-gray-700">
                        <Building2 size={15} />
                        {t('Company to configure', 'Empresa a configurar')}
                    </label>
                    <select
                        value={selectedEmpresaId || ''}
                        onChange={(e) => setSelectedEmpresaId(Number(e.target.value))}
                        className="h-11 w-full rounded-xl border border-gray-200 bg-white px-3 text-sm outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                    >
                        <option value="" disabled>
                            {t('Select a company', 'Selecciona una empresa')}
                        </option>
                        {empresas.map((emp) => (
                            <option key={emp.id} value={emp.id}>
                                {emp.nombre}
                            </option>
                        ))}
                    </select>
                </div>
            )}

            {selectedEmpresaId ? (
                <>
                    <div className="overflow-hidden rounded-2xl border border-gray-100 bg-white shadow-sm">
                        <div className="flex items-center gap-3 border-b border-gray-100 bg-gradient-to-r from-orange-50 to-amber-50 px-6 py-4">
                            <div className="rounded-xl bg-orange-100 p-2">
                                <Webhook size={18} className="text-orange-600" />
                            </div>
                            <div>
                                <h3 className="font-bold text-gray-900">
                                    {t('Automation Webhook (Zapier / Make)', 'Webhook de Automatización (Zapier / Make)')}
                                </h3>
                                <p className="mt-0.5 text-xs text-gray-500">
                                    {t(
                                        'Receive a clean POST after every completed or failed call. Connect to Zapier, Make, n8n, or any custom endpoint.',
                                        'Recibe un POST limpio tras cada llamada completada o fallida. Conecta con Zapier, Make, n8n o cualquier endpoint propio.',
                                    )}
                                </p>
                            </div>
                        </div>
                        <div className="space-y-5 p-6">
                            <div className="rounded-xl border border-gray-200 bg-gray-50 p-4">
                                <p className="mb-2 text-[11px] font-bold uppercase tracking-wider text-gray-400">
                                    {t('Example payload (POST JSON)', 'Ejemplo de payload (POST JSON)')}
                                </p>
                                <pre className="overflow-x-auto whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-gray-700">
{`{
  "event": "call.completed",
  "call_id": 123,
  "phone": "+34600000000",
  "status": "completed",
  "date": "2026-04-08T...",
  "campaign_name": "...",
  "datos_extra": { "interesado": true, "nota": 8 },
  "interesado": true,
  "nota": 8
}`}
                                </pre>
                            </div>

                            <div>
                                <label className="mb-2 block text-xs font-semibold uppercase tracking-wider text-gray-500">
                                    {t('Webhook URL', 'URL del Webhook')}
                                </label>
                                <div className="flex gap-2">
                                    <div className="relative flex-1">
                                        <LinkIcon size={15} className="absolute left-3 top-3 text-gray-400" />
                                        <input
                                            type="url"
                                            value={automationWebhookUrl}
                                            onChange={(e) => setAutomationWebhookUrl(e.target.value)}
                                            placeholder="https://hooks.zapier.com/hooks/catch/..."
                                            className="h-11 w-full rounded-xl border border-gray-200 pl-9 pr-3 text-sm outline-none transition-all focus:border-orange-400 focus:ring-2 focus:ring-orange-400/20"
                                        />
                                    </div>
                                    <button
                                        onClick={handleTestAutomation}
                                        disabled={!automationWebhookUrl}
                                        className="flex h-11 items-center gap-1.5 rounded-xl border border-orange-200 bg-orange-50 px-4 text-sm font-medium text-orange-700 transition-colors hover:bg-orange-100 disabled:opacity-40"
                                    >
                                        <Zap size={15} /> {t('Test')}
                                    </button>
                                </div>
                            </div>

                            <div className="flex items-center gap-3">
                                <a
                                    href="https://zapier.com/apps/webhook/integrations"
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="flex items-center gap-1.5 text-xs text-orange-600 hover:underline"
                                >
                                    <ExternalLink size={12} /> Zapier Webhooks
                                </a>
                                <span className="text-gray-300">·</span>
                                <a
                                    href="https://www.make.com/en/integrations/webhooks"
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="flex items-center gap-1.5 text-xs text-orange-600 hover:underline"
                                >
                                    <ExternalLink size={12} /> Make Webhooks
                                </a>
                            </div>

                            <div className="flex justify-end">
                                <button
                                    onClick={handleSaveAutomation}
                                    disabled={isSavingAutomation}
                                    className="flex h-10 items-center gap-2 rounded-xl bg-orange-600 px-5 text-sm font-semibold text-white transition-colors hover:bg-orange-700 disabled:opacity-50"
                                >
                                    {isSavingAutomation ? t('Saving...', 'Guardando...') : <><Save size={15} /> {t('Save Webhook', 'Guardar Webhook')}</>}
                                </button>
                            </div>
                        </div>
                    </div>

                    <div className="overflow-hidden rounded-2xl border border-gray-100 bg-white shadow-sm">
                        <div className="flex items-center gap-3 border-b border-gray-100 bg-gradient-to-r from-blue-50 to-indigo-50 px-6 py-4">
                            <div className="rounded-xl bg-blue-100 p-2">
                                <Database size={18} className="text-blue-600" />
                            </div>
                            <div>
                                <h3 className="font-bold text-gray-900">
                                    {t('CRM Integration', 'Integración CRM')}
                                </h3>
                                <p className="mt-0.5 text-xs text-gray-500">
                                    {t(
                                        'Choose a well-known CRM with API and connect your own webhook or middleware.',
                                        'Elige un CRM conocido con API y conecta tu propio webhook o middleware.',
                                    )}
                                </p>
                            </div>
                        </div>

                        <div className="space-y-5 p-6">
                            <div className="space-y-3">
                                <label className="block text-xs font-semibold uppercase tracking-wider text-gray-500">
                                    {t('CRM Type', 'Tipo de CRM')}
                                </label>
                                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                                    {CRM_OPTIONS.map((option) => (
                                        <CrmCard
                                            key={option.id}
                                            option={option}
                                            selected={crmType === option.id}
                                            onSelect={setCrmType}
                                        />
                                    ))}
                                </div>
                            </div>

                            <div>
                                <label className="mb-2 flex justify-between text-xs font-semibold uppercase tracking-wider text-gray-500">
                                    <span>{t('Webhook URL', 'Webhook URL')}</span>
                                    <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[10px] font-medium normal-case text-blue-500">
                                        {t('POST JSON', 'POST JSON')}
                                    </span>
                                </label>
                                <div className="flex gap-2">
                                    <div className="relative flex-1">
                                        <LinkIcon size={15} className="absolute left-3 top-3 text-gray-400" />
                                        <input
                                            type="url"
                                            value={webhookUrl}
                                            onChange={(e) => setWebhookUrl(e.target.value)}
                                            placeholder="https://n8n.ausarta.net/webhook/crm-sync"
                                            className="h-11 w-full rounded-xl border border-gray-200 pl-9 pr-3 text-sm outline-none transition-all focus:border-blue-400 focus:ring-2 focus:ring-blue-400/20"
                                        />
                                    </div>
                                    <button
                                        onClick={handleTestCrm}
                                        disabled={!webhookUrl}
                                        className="flex h-11 items-center gap-1.5 rounded-xl border border-gray-200 bg-gray-100 px-4 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-200 disabled:opacity-40"
                                    >
                                        <Zap size={15} /> {t('Test')}
                                    </button>
                                </div>
                            </div>

                            <div className="flex gap-3 rounded-xl border border-blue-100 bg-blue-50 p-4 text-sm text-blue-800">
                                <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-blue-500" />
                                <span>
                                    {t(
                                        'When a call completes, the backend sends lead data, scores, datos_extra and transcript to this URL. You can route it into HubSpot, Salesforce, Pipedrive, Zoho, Dynamics, Freshsales or your own middleware.',
                                        'Al completar una llamada, el backend envía datos del lead, puntuaciones, datos_extra y transcripción a esta URL. Puedes enrutarlo a HubSpot, Salesforce, Pipedrive, Zoho, Dynamics, Freshsales o a tu propio middleware.',
                                    )}
                                </span>
                            </div>

                            <div className="flex justify-end">
                                <button
                                    onClick={handleSaveCrm}
                                    disabled={isSavingCrm}
                                    className="flex h-10 items-center gap-2 rounded-xl bg-blue-600 px-5 text-sm font-semibold text-white transition-colors hover:bg-blue-700 disabled:opacity-50"
                                >
                                    {isSavingCrm ? t('Saving...', 'Guardando...') : <><Save size={15} /> {t('Save CRM Config', 'Guardar CRM')}</>}
                                </button>
                            </div>
                        </div>
                    </div>
                </>
            ) : (
                <div className="rounded-2xl border border-gray-100 bg-white p-10 text-center text-gray-400">
                    {t('Select a company to configure integrations.', 'Selecciona una empresa para configurar las integraciones.')}
                </div>
            )}
        </div>
    );
};

export default CrmIntegrationView;
