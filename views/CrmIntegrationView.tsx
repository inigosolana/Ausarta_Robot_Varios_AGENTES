import React, { useState, useEffect } from 'react';
import { Database, Link as LinkIcon, Save, Zap, Building2 } from 'lucide-react';
import toast from 'react-hot-toast';
import { supabase } from '../lib/supabase';
import { useAuth } from '../contexts/AuthContext';
import type { Empresa } from '../types';

const CrmIntegrationView: React.FC = () => {
    const { profile, isRole } = useAuth();
    const isPlatformOwner = isRole('superadmin') || (profile?.empresas?.nombre === 'Ausarta' && isRole('admin'));

    const [empresas, setEmpresas] = useState<Empresa[]>([]);
    const [selectedEmpresaId, setSelectedEmpresaId] = useState<number | null>(null);
    const [webhookUrl, setWebhookUrl] = useState('');
    const [crmType, setCrmType] = useState('hubspot');
    const [isSaving, setIsSaving] = useState(false);
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
            toast.error('Error al cargar empresas');
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
            .select('crm_type, crm_webhook_url')
            .eq('id', empresaId)
            .single();

        if (error) {
            console.error('Error loading CRM config:', error);
        } else if (data) {
            setCrmType(data.crm_type || 'hubspot');
            setWebhookUrl(data.crm_webhook_url || '');
        }
    };

    const handleSave = async () => {
        if (!selectedEmpresaId) return;

        setIsSaving(true);
        try {
            const { error } = await supabase
                .from('empresas')
                .update({
                    crm_type: crmType,
                    crm_webhook_url: webhookUrl
                })
                .eq('id', selectedEmpresaId);

            if (error) throw error;
            toast.success('Configuración CRM guardada correctamente');
        } catch (error) {
            console.error('Save error:', error);
            toast.error('Error al guardar la configuración');
        } finally {
            setIsSaving(false);
        }
    };

    const handleTest = async () => {
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
            }).then(res => {
                if (!res.ok) throw new Error('Webhook error');
                return res;
            }),
            {
                loading: 'Enviando payload de prueba al CRM...',
                success: 'Test exitoso: webhook respondió correctamente',
                error: 'Error: El webhook rechazó la petición o está inactivo'
            }
        );
    };

    if (isLoading) {
        return <div className="p-8 text-center text-gray-500">Cargando configuración...</div>;
    }

    return (
        <div className="space-y-6 animate-fade-in max-w-4xl">
            <div>
                <h2 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
                    <Database size={24} className="text-blue-500" />
                    Sincronización CRM Bidireccional
                </h2>
                <p className="text-gray-500 dark:text-gray-400 mt-1">Configura Webhooks de n8n o URLs directas para sincronizar los resultados y transcripciones automáticamente con el CRM cuando finalice cada encuesta.</p>
            </div>

            <div className="bg-white dark:bg-gray-800 p-6 rounded-xl border border-gray-100 dark:border-gray-700 shadow-sm">
                <div className="space-y-6">
                    {/* Empresa Selector for Admins */}
                    {isPlatformOwner && (
                        <div>
                            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2">
                                <Building2 size={16} />
                                Empresa a configurar
                            </label>
                            <select
                                value={selectedEmpresaId || ''}
                                onChange={(e) => setSelectedEmpresaId(Number(e.target.value))}
                                className="w-full h-10 px-3 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none transition-colors"
                            >
                                <option value="" disabled>Selecciona una empresa</option>
                                {empresas.map(emp => (
                                    <option key={emp.id} value={emp.id}>{emp.nombre}</option>
                                ))}
                            </select>
                        </div>
                    )}

                    {selectedEmpresaId ? (
                        <>
                            <div>
                                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                                    Tipo de CRM
                                </label>
                                <select
                                    value={crmType}
                                    onChange={(e) => setCrmType(e.target.value)}
                                    className="w-full h-10 px-3 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none transition-colors"
                                >
                                    <option value="hubspot">HubSpot</option>
                                    <option value="salesforce">Salesforce</option>
                                    <option value="custom">Otro (Webhook genérico, n8n, etc.)</option>
                                </select>
                            </div>

                            <div>
                                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex justify-between items-center">
                                    <span>Webhook URL (n8n o Directo)</span>
                                    <span className="text-xs text-blue-500 bg-blue-50 dark:bg-blue-900/30 px-2 py-1 rounded">Se enviará un POST JSON</span>
                                </label>
                                <div className="flex gap-2">
                                    <div className="relative flex-1">
                                        <LinkIcon size={16} className="absolute left-3 top-3 text-gray-400" />
                                        <input
                                            type="url"
                                            value={webhookUrl}
                                            onChange={(e) => setWebhookUrl(e.target.value)}
                                            placeholder="https://n8n.ausarta.net/webhook/crm-sync"
                                            className="w-full pl-9 pr-3 h-10 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none transition-colors"
                                        />
                                    </div>
                                    <button
                                        onClick={handleTest}
                                        disabled={!webhookUrl}
                                        className="flex items-center gap-2 px-4 h-10 bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 text-gray-700 dark:text-gray-200 border border-gray-200 dark:border-gray-600 rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
                                    >
                                        <Zap size={16} /> Test
                                    </button>
                                </div>
                            </div>

                            <div className="bg-gray-50 dark:bg-gray-800/50 p-4 rounded-lg border border-gray-200 dark:border-gray-700 mt-4 leading-relaxed text-sm text-gray-600 dark:text-gray-400">
                                <strong>¿Cómo funciona?</strong><br /> Al completar o fallar una llamada, el backend detectará esto y enviará inmediatamente los datos del lead, las puntuaciones, variables globales, y la transcripción a esta URL configurada. Desde allí, puedes usar <code className="bg-gray-200 dark:bg-gray-700 py-0.5 px-1 rounded">n8n</code> para empujar el cliente de vuelta al CRM y añadir logs al timeline del contacto automáticamente.
                            </div>

                            <div className="pt-4 border-t border-gray-100 dark:border-gray-700 flex justify-end">
                                <button
                                    onClick={handleSave}
                                    disabled={isSaving}
                                    className="flex items-center gap-2 px-6 h-10 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
                                >
                                    <Save size={16} />
                                    {isSaving ? 'Guardando...' : 'Guardar Configuración'}
                                </button>
                            </div>
                        </>
                    ) : (
                        <div className="text-center text-gray-500 dark:text-gray-400 py-4">
                            Selecciona una empresa para configurar la integración CRM.
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};

export default CrmIntegrationView;
