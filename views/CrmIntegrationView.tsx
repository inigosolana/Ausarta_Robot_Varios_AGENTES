import React, { useState, useEffect } from 'react';
import { Database, Link as LinkIcon, Save, Zap, Building2, Webhook, CheckCircle2, ExternalLink } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import toast from 'react-hot-toast';
import { supabase } from '../lib/supabase';
import { useAuth } from '../contexts/AuthContext';
import type { Empresa } from '../types';

const ZAPIER_TEST_PAYLOAD = {
    event: 'call.completed',
    call_id: 9999,
    phone: '+34600000000',
    status: 'completed',
    date: new Date().toISOString(),
    campaign_name: 'Campaña de Prueba',
    transcription: 'Hola, prueba de integración Zapier/Make exitosa.',
    datos_extra: {
        interesado: true,
        nota_satisfaccion: 8,
        motivo: 'Precio muy competitivo',
    },
    interesado: true,
    nota_satisfaccion: 8,
    motivo: 'Precio muy competitivo',
};

const CrmIntegrationView: React.FC = () => {
    const { profile, isPlatformOwner } = useAuth();
    const { t } = useTranslation();

    const [empresas, setEmpresas] = useState<Empresa[]>([]);
    const [selectedEmpresaId, setSelectedEmpresaId] = useState<number | null>(null);

    // CRM Section
    const [webhookUrl, setWebhookUrl] = useState('');
    const [crmType, setCrmType] = useState('hubspot');
    const [isSavingCrm, setIsSavingCrm] = useState(false);

    // Automation (Zapier / Make) Section
    const [automationWebhookUrl, setAutomationWebhookUrl] = useState('');
    const [isSavingAutomation, setIsSavingAutomation] = useState(false);

    const [isLoading, setIsLoading] = useState(true);

    useEffect(() => {
        if (isPlatformOwner) {
            loadEmpresas();
        } else if (profile?.empresa_id) {
            setSelectedEmpresaId(profile.empresa_id);
            loadIntegrationConfig(profile.empresa_id);
        } else {
            setIsLoading(false);
        }
    }, [profile, isPlatformOwner]);

    useEffect(() => {
        if (selectedEmpresaId) {
            loadIntegrationConfig(selectedEmpresaId);
        }
    }, [selectedEmpresaId]);

    const loadEmpresas = async () => {
        const { data, error } = await supabase.from('empresas').select('*').order('nombre');
        if (error) {
            toast.error(t('Error loading companies', 'Error al cargar empresas'));
        } else if (data) {
            setEmpresas(data);
            if (data.length > 0 && !selectedEmpresaId) {
                setSelectedEmpresaId(data[0].id);
            }
        }
        setIsLoading(false);
    };

    const loadIntegrationConfig = async (empresaId: number) => {
        const { data, error } = await supabase
            .from('empresas')
            .select('crm_type, crm_webhook_url, webhook_url')
            .eq('id', empresaId)
            .single();

        if (error) {
            console.error('Error loading integration config:', error);
        } else if (data) {
            setCrmType(data.crm_type || 'hubspot');
            setWebhookUrl(data.crm_webhook_url || '');
            setAutomationWebhookUrl(data.webhook_url || '');
        }
    };

    const handleSaveCrm = async () => {
        if (!selectedEmpresaId) return;
        setIsSavingCrm(true);
        try {
            const { error } = await supabase
                .from('empresas')
                .update({ crm_type: crmType, crm_webhook_url: webhookUrl })
                .eq('id', selectedEmpresaId);
            if (error) throw error;
            toast.success(t('CRM configuration saved', 'Configuración CRM guardada'));
        } catch (err) {
            toast.error(t('Error saving CRM config', 'Error al guardar configuración CRM'));
        } finally {
            setIsSavingCrm(false);
        }
    };

    const handleSaveAutomation = async () => {
        if (!selectedEmpresaId) return;
        setIsSavingAutomation(true);
        try {
            const { error } = await supabase
                .from('empresas')
                .update({ webhook_url: automationWebhookUrl || null })
                .eq('id', selectedEmpresaId);
            if (error) throw error;
            toast.success(t('Automation webhook saved', 'Webhook de automatización guardado'));
        } catch (err) {
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
                    transcription: 'Hola, prueba de integración CRM exitosa.'
                })
            }).then(res => { if (!res.ok) throw new Error(); }),
            {
                loading: t('Sending test to CRM...', 'Enviando prueba al CRM...'),
                success: t('CRM webhook responded correctly', 'El webhook CRM respondió correctamente'),
                error: t('Webhook rejected the request', 'El webhook rechazó la petición'),
            }
        );
    };

    const handleTestAutomation = () => {
        if (!automationWebhookUrl) return;
        toast.promise(
            fetch(automationWebhookUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(ZAPIER_TEST_PAYLOAD),
            }).then(res => { if (!res.ok) throw new Error(); }),
            {
                loading: t('Sending test to Zapier/Make...', 'Enviando prueba a Zapier/Make...'),
                success: t('Zapier/Make webhook responded correctly', 'El webhook respondió correctamente'),
                error: t('Webhook rejected the request', 'El webhook rechazó la petición'),
            }
        );
    };

    if (isLoading) {
        return <div className="p-8 text-center text-gray-500">{t('Loading configuration...', 'Cargando configuración...')}</div>;
    }

    const empresaSelector = isPlatformOwner && (
        <div className="mb-6">
            <label className="block text-sm font-medium text-gray-700 mb-2 flex items-center gap-2">
                <Building2 size={15} />
                {t('Company to configure', 'Empresa a configurar')}
            </label>
            <select
                value={selectedEmpresaId || ''}
                onChange={(e) => setSelectedEmpresaId(Number(e.target.value))}
                className="w-full h-10 px-3 rounded-lg border border-gray-200 bg-white text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
            >
                <option value="" disabled>{t('Select a company', 'Selecciona una empresa')}</option>
                {empresas.map(emp => (
                    <option key={emp.id} value={emp.id}>{emp.nombre}</option>
                ))}
            </select>
        </div>
    );

    return (
        <div className="space-y-8 animate-fade-in max-w-4xl">
            <div>
                <h2 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
                    <Database size={24} className="text-blue-500" />
                    {t('Integrations & Webhooks', 'Integraciones y Webhooks')}
                </h2>
                <p className="text-gray-500 mt-1">
                    {t('Connect call results to your CRM or automation tools automatically after each call.', 'Conecta los resultados de las llamadas a tu CRM o herramientas de automatización automáticamente tras cada llamada.')}
                </p>
            </div>

            {empresaSelector}

            {selectedEmpresaId ? (
                <>
                    {/* ── Section 1: Automation Webhook (Zapier / Make) ── */}
                    <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
                        <div className="px-6 py-4 border-b border-gray-100 bg-gradient-to-r from-orange-50 to-amber-50 flex items-center gap-3">
                            <div className="bg-orange-100 p-2 rounded-xl">
                                <Webhook size={18} className="text-orange-600" />
                            </div>
                            <div>
                                <h3 className="font-bold text-gray-900">{t('Automation Webhook (Zapier / Make)', 'Webhook de Automatización (Zapier / Make)')}</h3>
                                <p className="text-xs text-gray-500 mt-0.5">
                                    {t('Receive a clean POST after every completed or failed call. Connect to Zapier, Make, n8n, or any custom endpoint.', 'Recibe un POST limpio tras cada llamada completada o fallida. Conecta con Zapier, Make, n8n o cualquier endpoint propio.')}
                                </p>
                            </div>
                        </div>
                        <div className="p-6 space-y-5">
                            {/* Payload preview */}
                            <div className="bg-gray-50 rounded-xl border border-gray-200 p-4">
                                <p className="text-[11px] font-bold text-gray-400 uppercase tracking-wider mb-2">{t('Example payload (POST JSON)', 'Ejemplo de payload (POST JSON)')}</p>
                                <pre className="text-[11px] text-gray-700 font-mono overflow-x-auto leading-relaxed whitespace-pre-wrap">
{`{
  "event": "call.completed",
  "call_id": 123,
  "phone": "+34600000000",
  "status": "completed",
  "date": "2026-04-08T...",
  "campaign_name": "...",
  "datos_extra": { "interesado": true, "nota": 8 },
  "interesado": true,   // flattened for easy Zapier mapping
  "nota": 8
}`}
                                </pre>
                            </div>

                            <div>
                                <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
                                    {t('Webhook URL', 'URL del Webhook')}
                                </label>
                                <div className="flex gap-2">
                                    <div className="relative flex-1">
                                        <LinkIcon size={15} className="absolute left-3 top-2.5 text-gray-400" />
                                        <input
                                            type="url"
                                            value={automationWebhookUrl}
                                            onChange={(e) => setAutomationWebhookUrl(e.target.value)}
                                            placeholder="https://hooks.zapier.com/hooks/catch/..."
                                            className="w-full pl-9 pr-3 h-10 rounded-xl border border-gray-200 text-sm focus:border-orange-400 focus:ring-2 focus:ring-orange-400/20 outline-none transition-all"
                                        />
                                    </div>
                                    <button
                                        onClick={handleTestAutomation}
                                        disabled={!automationWebhookUrl}
                                        className="flex items-center gap-1.5 px-4 h-10 bg-orange-50 hover:bg-orange-100 text-orange-700 border border-orange-200 rounded-xl text-sm font-medium transition-colors disabled:opacity-40"
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
                                    className="flex items-center gap-2 px-5 h-10 bg-orange-600 hover:bg-orange-700 text-white rounded-xl text-sm font-semibold transition-colors disabled:opacity-50"
                                >
                                    {isSavingAutomation ? <>{t('Saving...', 'Guardando...')}</> : <><Save size={15} /> {t('Save Webhook', 'Guardar Webhook')}</>}
                                </button>
                            </div>
                        </div>
                    </div>

                    {/* ── Section 2: CRM (HubSpot / Salesforce / n8n) ── */}
                    <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
                        <div className="px-6 py-4 border-b border-gray-100 bg-gradient-to-r from-blue-50 to-indigo-50 flex items-center gap-3">
                            <div className="bg-blue-100 p-2 rounded-xl">
                                <Database size={18} className="text-blue-600" />
                            </div>
                            <div>
                                <h3 className="font-bold text-gray-900">{t('CRM Integration (HubSpot / Salesforce / n8n)', 'Integración CRM (HubSpot / Salesforce / n8n)')}</h3>
                                <p className="text-xs text-gray-500 mt-0.5">
                                    {t('Advanced CRM sync with type-specific payloads.', 'Sincronización CRM avanzada con payloads específicos por tipo.')}
                                </p>
                            </div>
                        </div>
                        <div className="p-6 space-y-5">
                            <div>
                                <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
                                    {t('CRM Type', 'Tipo de CRM')}
                                </label>
                                <select
                                    value={crmType}
                                    onChange={(e) => setCrmType(e.target.value)}
                                    className="w-full h-10 px-3 rounded-xl border border-gray-200 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
                                >
                                    <option value="hubspot">HubSpot</option>
                                    <option value="salesforce">Salesforce</option>
                                    <option value="custom">{t('Other / n8n / Generic', 'Otro / n8n / Genérico')}</option>
                                </select>
                            </div>

                            <div>
                                <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2 flex justify-between">
                                    <span>{t('Webhook URL', 'Webhook URL')}</span>
                                    <span className="text-[10px] text-blue-500 bg-blue-50 px-2 py-0.5 rounded-full normal-case font-medium">{t('POST JSON', 'POST JSON')}</span>
                                </label>
                                <div className="flex gap-2">
                                    <div className="relative flex-1">
                                        <LinkIcon size={15} className="absolute left-3 top-2.5 text-gray-400" />
                                        <input
                                            type="url"
                                            value={webhookUrl}
                                            onChange={(e) => setWebhookUrl(e.target.value)}
                                            placeholder="https://n8n.ausarta.net/webhook/crm-sync"
                                            className="w-full pl-9 pr-3 h-10 rounded-xl border border-gray-200 text-sm focus:border-blue-400 focus:ring-2 focus:ring-blue-400/20 outline-none transition-all"
                                        />
                                    </div>
                                    <button
                                        onClick={handleTestCrm}
                                        disabled={!webhookUrl}
                                        className="flex items-center gap-1.5 px-4 h-10 bg-gray-100 hover:bg-gray-200 text-gray-700 border border-gray-200 rounded-xl text-sm font-medium transition-colors disabled:opacity-40"
                                    >
                                        <Zap size={15} /> {t('Test')}
                                    </button>
                                </div>
                            </div>

                            <div className="bg-blue-50 border border-blue-100 rounded-xl p-4 flex gap-3 text-sm text-blue-800">
                                <CheckCircle2 size={16} className="text-blue-500 shrink-0 mt-0.5" />
                                <span>
                                    {t('When a call completes, the backend sends lead data, scores, datos_extra and transcript to this URL. Use n8n to route it into HubSpot/Salesforce contact timelines.', 'Al completar una llamada, el backend envía datos del lead, puntuaciones, datos_extra y transcripción a esta URL. Usa n8n para enrutarlo en las líneas de tiempo de HubSpot/Salesforce.')}
                                </span>
                            </div>

                            <div className="flex justify-end">
                                <button
                                    onClick={handleSaveCrm}
                                    disabled={isSavingCrm}
                                    className="flex items-center gap-2 px-5 h-10 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-sm font-semibold transition-colors disabled:opacity-50"
                                >
                                    {isSavingCrm ? t('Saving...', 'Guardando...') : <><Save size={15} /> {t('Save CRM Config', 'Guardar CRM')}</>}
                                </button>
                            </div>
                        </div>
                    </div>
                </>
            ) : (
                <div className="bg-white rounded-2xl border border-gray-100 p-10 text-center text-gray-400">
                    {t('Select a company to configure integrations.', 'Selecciona una empresa para configurar las integraciones.')}
                </div>
            )}
        </div>
    );
};

export default CrmIntegrationView;
