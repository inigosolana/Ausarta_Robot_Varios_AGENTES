import React, { useState, useEffect } from 'react';
import {
  Plus, Upload, Clock, AlertCircle, History, Trash2, X, Edit2, Building2, FileText, Target, ThumbsDown, Calendar,
  Bot, Users, CalendarClock, ChevronRight, ChevronLeft, Loader2, Check, Zap, FileSpreadsheet
} from 'lucide-react';
import toast from 'react-hot-toast';
import { useAuth } from '../contexts/AuthContext';
import { useTranslation } from 'react-i18next';
import { supabase } from '../lib/supabase';
import { fetchCampaignsList, fetchEmpresasList, fetchAgentsList } from '../lib/campaignsSupabase';
import { Empresa, SurveyResult } from '../types';
import DashboardView from './DashboardView';
import ResultsView from './ResultsView';
import { CallResultModal } from '../components/CallResultModal';

interface Campaign {
  id: number;
  name: string;
  status: string; // pending, running, completed, paused
  scheduled_time: string | null;
  created_at: string;
  empresa_id: number | null;
  total_leads?: number;
  called_leads?: number;
  failed_leads?: number;
  pending_leads?: number;
  retries_count?: number;
  interval_minutes?: number;
  is_question_based?: boolean;
  empresas?: { nombre: string };
  extraction_schema?: {key: string; type: string; label: string; options?: string[]}[];
}

interface Lead {
  id: number;
  phone_number: string;
  customer_name?: string;
  status: string; // pending, called, failed
  call_id?: number;
  updated_at?: string;
  puntuacion_comercial?: number;
  puntuacion_instalador?: number;
  puntuacion_rapidez?: number;
  comentarios?: string;
  transcription_preview?: string;
  retries_attempted?: number;
  tipo_resultados?: string;
  encuesta?: SurveyResult;
}

interface Agent {
  id: string;
  name: string;
}

export function CampaignsView() {
  const { profile, isRole, isPlatformOwner } = useAuth();
  const { t } = useTranslation();

  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [wizardStep, setWizardStep] = useState(0);
  const WIZARD_STEPS = [
    { id: 0, key: 'config', label: t('Configuración', 'Configuración'), icon: Bot },
    { id: 1, key: 'contacts', label: t('Contactos', 'Contactos'), icon: Users },
    { id: 2, key: 'schedule', label: t('Programación', 'Programación'), icon: CalendarClock },
  ] as const;
  const [agents, setAgents] = useState<Agent[]>([]);
  const [empresas, setEmpresas] = useState<Empresa[]>([]);
  const [selectedEmpresa, setSelectedEmpresa] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [listLoading, setListLoading] = useState(true);
  const [error, setError] = useState('');

  // Selected Campaign Details
  const [selectedCampaign, setSelectedCampaign] = useState<Campaign | null>(null);
  const [campaignLeads, setCampaignLeads] = useState<Lead[]>([]);
  const [showDetails, setShowDetails] = useState(false);

  // EDIT FEATURE
  const [editingCampaign, setEditingCampaign] = useState<Campaign | null>(null);
  const [editName, setEditName] = useState("");
  const [editTime, setEditTime] = useState("");
  const [activeTab, setActiveTab] = useState<'leads' | 'overview' | 'results'>('leads');
  // Modal de transcripción para la tabla de leads de campaña
  const [viewingTranscriptLead, setViewingTranscriptLead] = useState<SurveyResult | null>(null);

  function getScoreColor(score: number | null): string {
    if (score === null || Number.isNaN(score)) return 'bg-gray-50 text-gray-400 border border-gray-100';
    if (score >= 9) return 'bg-green-100 text-green-700 border border-green-200';
    if (score >= 7) return 'bg-blue-100 text-blue-700 border border-blue-200';
    if (score >= 5) return 'bg-yellow-100 text-yellow-700 border border-yellow-200';
    return 'bg-red-100 text-red-700 border border-red-200';
  }


  // Form State
  const [name, setName] = useState('');
  const [selectedAgent, setSelectedAgent] = useState('');
  const [dataSource, setDataSource] = useState<'csv' | 'api' | 'manual'>('csv');
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [manualInput, setManualInput] = useState('');
  const [scheduledTime, setScheduledTime] = useState('');
  const [retryInterval, setRetryInterval] = useState<number>(60);
  const [retryUnit, setRetryUnit] = useState<'minutes' | 'hours' | 'days'>('minutes');
  const [retriesCount, setRetriesCount] = useState<number>(3);
  const [editRetryInterval, setEditRetryInterval] = useState<number>(60);
  const [editRetryUnit, setEditRetryUnit] = useState<'minutes' | 'hours' | 'days'>('minutes');
  const [editRetriesCount, setEditRetriesCount] = useState<number>(3);
  const [intervalMinutes, setIntervalMinutes] = useState<number>(2);
  const [editIntervalMinutes, setEditIntervalMinutes] = useState<number>(2);
  const [scheduleMode, setScheduleMode] = useState<'now' | 'later'>('now');
  const [csvLeadCount, setCsvLeadCount] = useState<number | null>(null);
  const [csvParsing, setCsvParsing] = useState(false);
  const [csvDragActive, setCsvDragActive] = useState(false);

  // Dynamic Schema Extraction State
  const [extractionSchema, setExtractionSchema] = useState<{key: string; type: string; label: string; options?: string[]}[]>([]);
  const [editExtractionSchema, setEditExtractionSchema] = useState<{key: string; type: string; label: string; options?: string[]}[]>([]);

  const API_URL = (import.meta as any).env.VITE_API_URL || window.location.origin;

  const openEditModal = (camp: Campaign) => {
    setEditingCampaign(camp);
    setEditName(camp.name);
    if (camp.scheduled_time) {
      const date = new Date(camp.scheduled_time);
      const localISO = new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
      setEditTime(localISO);
    } else {
      setEditTime("");
    }

    // Set retry interval and unit if available
    if ((camp as any).retry_unit) {
      setEditRetryUnit((camp as any).retry_unit);
      const rawInterval = (camp as any).retry_interval || 60;
      const unit = (camp as any).retry_unit;
      if (unit === 'days') setEditRetryInterval(Math.floor(rawInterval / 86400));
      else if (unit === 'hours') setEditRetryInterval(Math.floor(rawInterval / 3600));
      else setEditRetryInterval(Math.floor(rawInterval / 60));
    } else {
      // Legacy or default
      setEditRetryInterval(Math.floor(((camp as any).retry_interval || 3600) / 60));
      setEditRetryUnit('minutes');
    }
    setEditRetriesCount((camp as any).retries_count || 3);
    setEditIntervalMinutes(camp.interval_minutes || 2);
    setEditExtractionSchema(camp.extraction_schema || []);
  };

  const handleUpdateCampaign = async () => {
    if (!editingCampaign) return;
    try {
      const payload = {
        name: editName,
        scheduled_time: editTime ? new Date(editTime).toISOString() : null,
        retry_interval: editRetryInterval,
        retry_unit: editRetryUnit,
        retries_count: editRetriesCount,
        interval_minutes: editIntervalMinutes,
        extraction_schema: editExtractionSchema.length > 0 ? editExtractionSchema : null
      };
      const res = await fetch(`${API_URL}/api/campaigns/${editingCampaign.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (res.ok) {
        toast.success(t("Campaign updated!", "¡Campaña actualizada!"));
        setEditingCampaign(null);
        loadCampaigns();
        if (selectedCampaign && selectedCampaign.id === editingCampaign.id) {
          const updatedCamp = await (await fetch(`${API_URL}/api/campaigns/${editingCampaign.id}`)).json();
          setSelectedCampaign(updatedCamp.campaign);
        }
      } else {
        toast.error(t("Update failed", "Error al actualizar"));
      }
    } catch (e) {
      toast.error(t("Error updating campaign", "Error al actualizar la campaña"));
    }
  };



  // Helper to group campaigns
  const groupedCampaignsByCompany = campaigns.reduce((acc: Record<string, Campaign[]>, campaign) => {
    const companyName = campaign.empresas?.nombre || t("General / No Company", "General / Sin Empresa");
    if (!acc[companyName]) {
      acc[companyName] = [];
    }
    acc[companyName].push(campaign);
    return acc;
  }, {} as Record<string, Campaign[]>);

  const groupedEntries = Object.entries(groupedCampaignsByCompany) as [string, Campaign[]][];

  useEffect(() => {
    loadCampaigns();
    loadEmpresas();

    // Supabase Realtime for Campaigns
    const channel = supabase
      .channel('campaigns-realtime-updates')
      .on(
        'postgres_changes',
        {
          event: '*',
          schema: 'public',
          table: 'campaigns',
          filter: profile?.empresa_id && !isPlatformOwner ? `empresa_id=eq.${profile.empresa_id}` : undefined
        },
        (payload) => {
          if (payload.eventType === 'UPDATE') {
            setCampaigns(prev => prev.map(c => c.id === payload.new.id ? { ...c, ...payload.new } : c));
            if (selectedCampaign && selectedCampaign.id === payload.new.id) {
              setSelectedCampaign(prev => prev ? { ...prev, ...payload.new } : null);
            }
          } else if (payload.eventType === 'INSERT') {
            setCampaigns(prev => [payload.new as Campaign, ...prev]);
          } else if (payload.eventType === 'DELETE') {
            setCampaigns(prev => prev.filter(c => c.id !== payload.old.id));
          }
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [profile, isPlatformOwner]);

  useEffect(() => {
    loadAgents();
  }, [profile, isPlatformOwner, selectedEmpresa]);

  const loadEmpresas = async () => {
    try {
      const empresaFilter = !isPlatformOwner && profile?.empresa_id ? profile.empresa_id : undefined;
      const data = await fetchEmpresasList(empresaFilter);
      setEmpresas(data as Empresa[]);
    } catch (e) {
      console.error('Error loading empresas from Supabase:', e);
      setEmpresas([]);
    }
  };

  const loadAgents = async () => {
    try {
      const empresaFilter =
        !isPlatformOwner && profile?.empresa_id
          ? profile.empresa_id
          : isPlatformOwner && selectedEmpresa
            ? selectedEmpresa
            : undefined;
      const data = await fetchAgentsList(empresaFilter);
      setAgents(data);
      if (data.length > 0) setSelectedAgent(data[0].id);
      else setSelectedAgent('');
    } catch (e) {
      console.error('Error loading agents from Supabase:', e);
      setAgents([]);
    }
  };

  const loadCampaigns = async () => {
    setListLoading(true);
    try {
      const empresaFilter = !isPlatformOwner && profile?.empresa_id ? profile.empresa_id : undefined;
      const data = await fetchCampaignsList(empresaFilter);
      setCampaigns(data as Campaign[]);
    } catch (e) {
      console.error('Error loading campaigns from Supabase:', e);
      setCampaigns([]);
    } finally {
      setListLoading(false);
    }
  };

  const loadCampaignDetails = async (campaign: Campaign) => {
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/campaigns/${campaign.id}`);
      if (res.ok) {
        const data = await res.json();
        setSelectedCampaign(data.campaign);
        setCampaignLeads(data.leads || []);
        setShowDetails(true);
        setActiveTab('leads');
      }
    } catch (e) {
      toast.error(t("Error loading details", "Error al cargar detalles"));
    } finally {
      setLoading(false);
    }
  };

  const parseLines = (text: string): { phone_number: string, customer_name?: string }[] => {
    const lines = text.split('\n');
    const results: { phone_number: string, customer_name?: string }[] = [];

    lines.forEach((line, index) => {
      // Ignorar cabecera si incluye 'phone'
      if (index === 0 && line.toLowerCase().includes('phone') && line.toLowerCase().includes(',')) return;

      const parts = line.split(',');
      if (parts.length >= 1) {
        const rawPhone = parts[0];
        const rawName = parts.length > 1 ? parts[1] : '';

        const phone = rawPhone.trim().replace(/[^0-9+]/g, '');
        let name = rawName.trim().replace(/^["']|["']$/g, '');

        if (phone.length > 5) {
          results.push({
            phone_number: phone,
            customer_name: name || undefined
          });
        }
      }
    });
    return results;
  };

  const parseCSV = (file: File): Promise<{ phone_number: string, customer_name?: string }[]> => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = (e) => {
        const text = e.target?.result as string;
        resolve(parseLines(text));
      };
      reader.onerror = reject;
      reader.readAsText(file);
    });
  };

  const handleCreateNewForCompany = (empId: number) => {
    setSelectedEmpresa(empId);
    setWizardStep(0);
    setShowCreate(true);
  };

  const resetWizard = () => {
    setWizardStep(0);
    setName('');
    setSelectedAgent('');
    setCsvFile(null);
    setCsvLeadCount(null);
    setCsvParsing(false);
    setCsvDragActive(false);
    setManualInput('');
    setScheduledTime('');
    setScheduleMode('now');
    setError('');
    setDataSource('csv');
  };

  const processCsvFile = async (file: File) => {
    setCsvFile(file);
    setCsvParsing(true);
    setCsvLeadCount(null);
    try {
      const leads = await parseCSV(file);
      setCsvLeadCount(leads.length);
    } catch {
      setCsvLeadCount(0);
    } finally {
      setCsvParsing(false);
    }
  };

  const CampaignProgressBar = ({ called, total }: { called: number; total: number }) => {
    const pct = total > 0 ? Math.min(100, (called / total) * 100) : 0;
    return (
      <div className="space-y-1.5 min-w-[140px]">
        <div className="h-2 w-full bg-slate-100 rounded-full overflow-hidden">
          <div
            className="h-full bg-gradient-to-r from-indigo-500 to-emerald-500 rounded-full transition-all duration-700 ease-out"
            style={{ width: `${pct}%` }}
          />
        </div>
        <p className="text-xs text-slate-500 tabular-nums">
          {called} / {total} {t('calls processed', 'llamadas procesadas')}
        </p>
      </div>
    );
  };

  const canWizardNext = () => {
    if (wizardStep === 0) return Boolean(name.trim() && selectedAgent);
    if (wizardStep === 1) {
      if (dataSource === 'csv') return Boolean(csvFile);
      if (dataSource === 'manual') return manualInput.trim().length > 0;
      return true;
    }
    return true;
  };

  const handleCreate = async () => {
    if (!name || !selectedAgent) {
      setError(t('Please complete the required fields', 'Por favor, completa los campos requeridos'));
      return;
    }

    setLoading(true);
    setError('');

    try {
      let leads: { phone_number: string, customer_name?: string }[] = [];

      if (dataSource === 'csv' && csvFile) {
        leads = await parseCSV(csvFile);
      } else if (dataSource === 'csv' && !csvFile) {
        throw new Error(t("Please upload a CSV file", "Por favor, sube un archivo CSV"));
      } else if (dataSource === 'manual') {
        leads = parseLines(manualInput);
        if (leads.length === 0) throw new Error(t("Please enter at least one valid phone number", "Por favor, introduce al menos un número de teléfono válido"));
      }

      const selectedAgentData = agents.find(a => String(a.id) === String(selectedAgent));

      const payload = {
        campaign: {
          name,
          agent_id: selectedAgent,
          empresa_id: selectedEmpresa || (selectedAgentData ? (selectedAgentData as any).empresa_id : profile?.empresa_id),
          scheduled_time: scheduleMode === 'later' && scheduledTime ? new Date(scheduledTime).toISOString() : null,
          status: 'pending',
          retry_interval: retryInterval || 60,
          retry_unit: retryUnit,
          retries_count: retriesCount,
          interval_minutes: intervalMinutes,
          extraction_schema: extractionSchema.length > 0 ? extractionSchema : null
        },
        leads
      };


      const res = await fetch(`${API_URL}/api/campaigns`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (!res.ok) throw new Error(t('Error creating campaign', 'Error al crear la campaña'));

      setShowCreate(false);
      setName('');
      setCsvFile(null);
      setExtractionSchema([]);
      loadCampaigns();
      toast.success(t('Campaign created successfully!', '¡Campaña creada exitosamente!'));

    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm(t("Are you sure you want to delete this campaign? This cannot be undone.", "¿Estás seguro de que quieres eliminar esta campaña? Esto no se puede deshacer."))) return;
    try {
      await fetch(`${API_URL}/api/campaigns/${id}`, { method: 'DELETE' });
      loadCampaigns();
      if (selectedCampaign?.id === id) setShowDetails(false);
    } catch (e) {
      toast.error(t("Error deleting campaign", "Error al eliminar la campaña"));
    }
  };

  const handleRetryFailed = async (id: number) => {
    if (!confirm(t("Are you sure you want to retry all failed calls in this campaign?", "¿Estás seguro de que quieres reintentar todas las llamadas fallidas en esta campaña?"))) return;
    try {
      const res = await fetch(`${API_URL}/api/campaigns/${id}/retry`, { method: 'POST' });
      const data = await res.json();

      if (res.ok && data.status === 'success') {
        toast.success(t(`Successfully queued ${data.retried_count} failed calls for retry.`, `Se han encolado exitosamente ${data.retried_count} llamadas fallidas para reintento.`));
        if (selectedCampaign) loadCampaignDetails(selectedCampaign);
        loadCampaigns();
      } else {
        toast.error(t("Failed to retry calls.", "Error al reintentar llamadas."));
      }
    } catch (e) {
      toast.error(t("Error connecting to server", "Error al conectar con el servidor"));
    }
  };

  const handleRetryLead = async (leadId: number) => {
    try {
      const res = await fetch(`${API_URL}/api/campaigns/leads/${leadId}/retry`, { method: 'POST' });
      if (res.ok) {
        // Optimistic update
        setCampaignLeads(prev => prev.map(l =>
          l.id === leadId ? { ...l, status: 'pending', retries_attempted: 0 } : l
        ));
        toast.success(t("Lead requeued successfully!", "Lead encolado exitosamente!"));
      } else {
        toast.error(t("Failed to retry lead", "Error al reintentar lead"));
      }
    } catch (e) {
      toast.error(t("Error connecting to server", "Error al conectar con el servidor"));
    }
  };

  const handleStartCampaign = async (campaignId: number) => {
    try {
      const res = await fetch(`${API_URL}/api/campaigns/${campaignId}/start`, { method: 'POST' });
      if (res.ok) {
        toast.success(t("Campaign started (Drip mode active)", "Campaña iniciada (Modo Goteo activo)"));
        loadCampaigns();
        if (selectedCampaign?.id === campaignId) loadCampaignDetails(selectedCampaign);
      } else {
        toast.error(t("Error starting campaign", "Error al iniciar campaña"));
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleStopCampaign = async (campaignId: number) => {
    try {
      const res = await fetch(`${API_URL}/api/campaigns/${campaignId}/stop`, { method: 'POST' });
      if (res.ok) {
        toast.success(t("Campaign paused", "Campaña pausada"));
        loadCampaigns();
        if (selectedCampaign?.id === campaignId) loadCampaignDetails(selectedCampaign);
      } else {
        toast.error(t("Error pausing campaign", "Error al pausar campaña"));
      }
    } catch (e) {
      console.error(e);
    }
  };

  // --- UI Components ---

  const renderEditModal = () => {
    if (!editingCampaign) return null;
    return (
      <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
        <div className="bg-white rounded-xl shadow-2xl max-w-md w-full overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-100 flex justify-between items-center bg-gray-50">
            <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
              <Edit2 className="w-5 h-5 text-blue-600" /> {t("Edit Campaign", "Editar Campaña")}
            </h3>
            <button
              onClick={() => setEditingCampaign(null)}
              className="text-gray-400 hover:text-gray-600 transition-colors"
            >
              <X className="w-6 h-6" />
            </button>
          </div>
          <div className="p-6 space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t("Campaign Name", "Nombre de la Campaña")}</label>
              <input
                type="text"
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 outline-none"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t("Scheduled Time", "Hora Programada")}</label>
              <input
                type="datetime-local"
                value={editTime}
                onChange={(e) => setEditTime(e.target.value)}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 outline-none"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t("Retry Interval", "Intervalo de Reintento")}</label>
              <div className="flex gap-2">
                <input
                  type="number"
                  min="1"
                  value={editRetryInterval}
                  onChange={(e) => setEditRetryInterval(Number(e.target.value))}
                  className="flex-1 px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 outline-none"
                />
                <select
                  value={editRetryUnit}
                  onChange={(e) => setEditRetryUnit(e.target.value as any)}
                  className="w-1/3 px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 outline-none"
                >
                  <option value="minutes">{t("Minutes", "Minutos")}</option>
                  <option value="hours">{t("Hours", "Horas")}</option>
                  <option value="days">{t("Days", "Dias")}</option>
                </select>
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t("Number of Retries", "Número de Reintentos")}</label>
              <input
                type="number"
                min="0"
                max="10"
                value={editRetriesCount}
                onChange={(e) => setEditRetriesCount(Number(e.target.value))}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 outline-none"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t("Drip Interval (Minutes)", "Intervalo de Goteo (Minutos)")}</label>
              <input
                type="number"
                min="1"
                value={editIntervalMinutes}
                onChange={(e) => setEditIntervalMinutes(Number(e.target.value))}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 outline-none"
              />
              <p className="text-[10px] text-gray-400 mt-1">{t("Wait time between each call in the campaign.", "Tiempo de espera entre cada llamada de la campaña.")}</p>
            </div>

            <div className="border-t border-gray-100 pt-4">
              <h3 className="text-sm font-medium text-gray-700 mb-1">{t("Dynamic Data Extraction", "Extracción de Datos Dinámica")}</h3>
              <p className="text-xs text-gray-500 mb-2">{t("Edit the fields the AI extracts:", "Edita los campos que extrae la IA:")}</p>
              <div className="space-y-2 max-h-48 overflow-y-auto pr-1">
                {editExtractionSchema.map((field, index) => (
                  <div key={index} className="flex flex-col gap-1 bg-gray-50 p-2 rounded border border-gray-200">
                    <div className="flex gap-2 w-full">
                      <input type="text" placeholder="Key" className="flex-1 text-xs px-2 py-1 border rounded" value={field.key} onChange={(e) => {
                        const newSchema = [...editExtractionSchema];
                        newSchema[index].key = e.target.value.replace(/\s+/g, '_').toLowerCase();
                        setEditExtractionSchema(newSchema);
                      }} />
                      <input type="text" placeholder="Label" className="flex-1 text-xs px-2 py-1 border rounded" value={field.label} onChange={(e) => {
                        const newSchema = [...editExtractionSchema];
                        newSchema[index].label = e.target.value;
                        setEditExtractionSchema(newSchema);
                      }} />
                      <select className="w-24 text-xs px-1 py-1 border rounded" value={field.type} onChange={(e) => {
                        const newSchema = [...editExtractionSchema];
                        newSchema[index].type = e.target.value;
                        if(e.target.value !== 'enum') delete newSchema[index].options;
                        else newSchema[index].options = [];
                        setEditExtractionSchema(newSchema);
                      }}>
                        <option value="text">Texto</option>
                        <option value="number">Núm</option>
                        <option value="boolean">Bool</option>
                        <option value="enum">Enum</option>
                      </select>
                      <button onClick={() => setEditExtractionSchema(editExtractionSchema.filter((_, i) => i !== index))} className="p-1 px-1 text-red-500 hover:bg-red-100 rounded">
                        <Trash2 className="w-3 h-3" />
                      </button>
                    </div>
                    {field.type === 'enum' && (
                      <input type="text" placeholder="Opciones separadas por coma" className="w-full text-xs px-2 py-1 border rounded bg-white" value={field.options?.join(', ') || ''} onChange={(e) => {
                        const newSchema = [...editExtractionSchema];
                        newSchema[index].options = e.target.value.split(',').map(s=>s.trim()).filter(Boolean);
                        setEditExtractionSchema(newSchema);
                      }} />
                    )}
                  </div>
                ))}
              </div>
              <button onClick={() => setEditExtractionSchema([...editExtractionSchema, {key: '', label: '', type: 'text'}])} className="mt-2 text-xs bg-white text-blue-600 px-3 py-1.5 rounded-lg border border-dashed border-blue-300 hover:bg-blue-50 flex items-center gap-1 font-medium w-full justify-center">
                <Plus className="w-3 h-3" /> Añadir Dato
              </button>
            </div>
          </div>
          <div className="px-6 py-4 bg-gray-50 border-t border-gray-100 flex justify-end gap-3">
            <button onClick={() => setEditingCampaign(null)} className="px-4 py-2 text-gray-700">{t("Cancel", "Cancelar")}</button>
            <button onClick={handleUpdateCampaign} className="px-6 py-2 bg-blue-600 text-white rounded-lg">{t("Save Changes", "Guardar Cambios")}</button>
          </div>
        </div>
      </div>
    );
  };

  const StatusBadge = ({ status }: { status: string }) => {
    const colors: Record<string, string> = {
      pending: 'bg-yellow-100 text-yellow-800 ring-1 ring-yellow-200',
      running: 'bg-blue-100 text-blue-800 ring-1 ring-blue-200',
      completed: 'bg-green-100 text-green-800 ring-1 ring-green-200',
      paused: 'bg-yellow-50 text-yellow-700 ring-1 ring-yellow-200',
      called: 'bg-blue-100 text-blue-800',
      failed: 'bg-red-100 text-red-800',
      unreached: 'bg-orange-100 text-orange-800',
      incomplete: 'bg-purple-100 text-purple-800',
      rejected_opt_out: 'bg-red-200 text-red-900',
    };
    const labels: Record<string, string> = {
      unreached: 'No Contestó',
      incomplete: 'Incompleta',
      rejected_opt_out: 'Rechazada',
      called: 'Llamada',
      completed: 'Completada',
      failed: 'Fallida',
      pending: 'Pendiente',
      running: 'En Curso',
      paused: 'Pausada',
    };
    return (
      <span className={`px-2 py-1 rounded-full text-xs font-medium ${colors[status] || colors.pending}`}>
        {labels[status] || status}
      </span>
    );
  };

  if (showDetails && selectedCampaign) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <button onClick={() => setShowDetails(false)} className="text-gray-500 hover:text-gray-900 flex items-center gap-2">
            ← {t("Back to Campaigns", "Volver a Campañas")}
          </button>
          <div className='flex gap-2'>
            <button
              onClick={() => loadCampaignDetails(selectedCampaign)}
              className="px-3 py-1 bg-gray-100 text-gray-700 rounded hover:bg-gray-200 text-sm flex items-center gap-1"
            >
              <History className="w-4 h-4" /> {t("Update", "Actualizar")}
            </button>

            <button
              onClick={() => openEditModal(selectedCampaign)}
              className="px-3 py-1 bg-blue-100 text-blue-700 rounded hover:bg-blue-200 text-sm flex items-center gap-1"
            >
              <Edit2 className="w-4 h-4" /> {t("Edit", "Editar")}
            </button>

            {/* Retry Button - Only show if there are failed/unreached/incomplete leads */}
            {(selectedCampaign.failed_leads || 0) > 0 && (
              <button
                onClick={() => handleRetryFailed(selectedCampaign.id)}
                className="px-3 py-1 bg-yellow-100 text-yellow-700 rounded hover:bg-yellow-200 text-sm flex items-center gap-1"
              >
                <Clock className="w-4 h-4" /> {t("Retry Failed", "Reintentar Fallidas")} ({selectedCampaign.failed_leads})
              </button>
            )}

            <button
              onClick={() => handleDelete(selectedCampaign.id)}
              className="px-3 py-1 bg-red-100 text-red-700 rounded hover:bg-red-200 text-sm flex items-center gap-1"
            >
              <Trash2 className="w-4 h-4" /> {t("Delete Campaign", "Eliminar Campaña")}
            </button>

            {selectedCampaign.status === 'running' || selectedCampaign.status === 'active' ? (
              <button
                onClick={() => handleStopCampaign(selectedCampaign.id)}
                className="px-4 py-1 bg-orange-600 text-white rounded hover:bg-orange-700 text-sm flex items-center gap-2 font-bold shadow-sm"
              >
                <X className="w-4 h-4" /> {t("Stop Drip", "Pausar Goteo")}
              </button>
            ) : (
              <button
                onClick={() => handleStartCampaign(selectedCampaign.id)}
                className="px-4 py-1 bg-green-600 text-white rounded hover:bg-green-700 text-sm flex items-center gap-2 font-bold shadow-sm"
              >
                <Plus className="w-4 h-4" /> {t("Start Drip", "Iniciar Goteo")}
              </button>
            )}
          </div>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-gray-100 mb-6">
          <button
            onClick={() => setActiveTab('leads')}
            className={`px-6 py-3 text-sm font-medium transition-colors border-b-2 ${activeTab === 'leads' ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'}`}
          >
            {t("List of Leads", "Lista de Leads")}
          </button>
          <button
            onClick={() => setActiveTab('overview')}
            className={`px-6 py-3 text-sm font-medium transition-colors border-b-2 ${activeTab === 'overview' ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'}`}
          >
            Overview
          </button>
          <button
            onClick={() => setActiveTab('results')}
            className={`px-6 py-3 text-sm font-medium transition-colors border-b-2 ${activeTab === 'results' ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'}`}
          >
            {t("Detailed Results", "Resultados Detallados")}
          </button>
        </div>

        {activeTab === 'overview' && (
          <DashboardView
            campaignId={selectedCampaign.id}
            title={`Dashboard: ${selectedCampaign.name}`}
            hideIntegrations={true}
          />
        )}

        {activeTab === 'results' && (
          <ResultsView
            campaignId={selectedCampaign.id}
            title={`Resultados: ${selectedCampaign.name}`}
            hideHeader={true}
            schema={selectedCampaign.extraction_schema}
          />
        )}

        {activeTab === 'leads' && (
          <>
            {/* Info Cards */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              <div className="bg-blue-50 p-4 rounded-xl border border-blue-100">
                <p className="text-blue-600 text-xs font-semibold uppercase">Total Leads</p>
                <p className="text-2xl font-bold text-blue-900">{selectedCampaign.total_leads || 0}</p>
              </div>
              <div className="bg-green-50 p-4 rounded-xl border border-green-100">
                <p className="text-green-600 text-xs font-semibold uppercase">{t("Calls", "Llamadas")}</p>
                <p className="text-2xl font-bold text-green-900">{selectedCampaign.called_leads || 0}</p>
              </div>
              <div className="bg-yellow-50 p-4 rounded-xl border border-yellow-100">
                <p className="text-yellow-600 text-xs font-semibold uppercase">{t("Pending", "Pendientes")}</p>
                <p className="text-2xl font-bold text-yellow-900">{selectedCampaign.pending_leads || 0}</p>
              </div>
              <div className="bg-red-50 p-4 rounded-xl border border-red-100">
                <p className="text-red-600 text-xs font-semibold uppercase">{t("Failed", "Fallidas")}</p>
                <p className="text-2xl font-bold text-red-900">{selectedCampaign.failed_leads || 0}</p>
              </div>
            </div>

            <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
              <div className="px-6 py-4 border-b border-gray-100 flex justify-between items-center">
                <h3 className="font-semibold text-gray-900">{t("Call Log and Results", "Registro de Llamadas y Resultados")}</h3>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead className="bg-gray-50 border-b border-gray-100">
                    <tr>
                      <th className="px-6 py-3 text-left text-xs font-semibold text-gray-500 uppercase">{t("Name", "Nombre")}</th>
                      <th className="px-6 py-3 text-left text-xs font-semibold text-gray-500 uppercase">{t("Phone", "Teléfono")}</th>
                      <th className="px-6 py-3 text-left text-xs font-semibold text-gray-500 uppercase">{t("Status and Attempts", "Estado e Intentos")}</th>
                      <th className="px-6 py-3 text-left text-xs font-semibold text-gray-500 uppercase w-1/3">{t("Notes and Transcription", "Notas y Transcripción")}</th>
                      <th className="px-6 py-3 text-left text-xs font-semibold text-gray-500 uppercase">{t("Last Update", "Última Actualización")}</th>
                      <th className="px-6 py-3 text-right text-xs font-semibold text-gray-500 uppercase">{t("Actions", "Acciones")}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {campaignLeads.map((lead) => (
                      <tr key={lead.id} className="hover:bg-gray-50">
                        <td className="px-6 py-4 text-sm font-medium text-gray-900">{lead.customer_name || '-'}</td>
                        <td className="px-6 py-4 text-sm text-gray-500">{lead.phone_number}</td>
                        <td className="px-6 py-4">
                          <div className="flex flex-col gap-1 items-start">
                            <span className={`px-2 py-1 rounded-full text-xs font-medium 
                                        ${lead.status === 'completed' ? 'bg-green-100 text-green-800' :
                                lead.status === 'called' ? 'bg-blue-100 text-blue-800' :
                                  lead.status === 'failed' ? 'bg-purple-100 text-purple-900' :
                                    lead.status === 'unreached' ? 'bg-amber-100 text-amber-900' :
                                      lead.status === 'incomplete' ? 'bg-blue-50 text-blue-800' :
                                        (lead.status === 'rejected_opt_out' || lead.status === 'rejected') ? 'bg-red-100 text-red-800' : 'bg-gray-100 text-gray-800'}`}>
                              {lead.status === 'unreached' ? t('No Answer', 'No Contesta') :
                                (lead.status === 'rejected_opt_out' || lead.status === 'rejected') ? t('Rejected', 'Rechazada') :
                                  lead.status === 'completed' ? t('Completed', 'Completada') :
                                    lead.status === 'incomplete' ? t('Incomplete', 'Incompleta') :
                                      lead.status === 'failed' ? t('Failed', 'Fallida') :
                                        lead.status === 'called' ? t('Called', 'Llamada') :
                                          lead.status === 'pending' ? t('Pending', 'Pendiente') : lead.status}
                            </span>
                            {/* Mostrar intentos si > 0 */}
                            {(lead.retries_attempted || 0) > 0 && (
                              <span className="text-xs text-gray-500 flex items-center gap-1">
                                <History className="w-3 h-3" /> {t("Attempt", "Intento")}: {lead.retries_attempted}
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="px-6 py-4 text-sm text-gray-600">
                          {/* Columnas de Resultados Profesionales */}
                          {(lead.status === 'completed' || lead.status === 'completada') ? (
                            <div className="flex flex-col gap-2">
                              {lead.encuesta?.tipo_resultados === 'CUALIFICACION_LEAD' ? (
                                <div className="flex items-center gap-1.5">
                                  {lead.encuesta.datos_extra?.lead_cualificado ? (
                                    <span className="bg-green-100 text-green-700 text-[10px] px-2 py-0.5 rounded-full font-bold flex items-center gap-1 border border-green-200 shadow-sm">
                                      <Target size={12} /> {t('QUALIFIED', 'CUALIFICADO')}
                                    </span>
                                  ) : (
                                    <span className="bg-red-100 text-red-700 text-[10px] px-2 py-0.5 rounded-full font-bold flex items-center gap-1 border border-red-200 shadow-sm">
                                      <ThumbsDown size={12} /> {t('DISCARDED', 'DESCARTADO')}
                                    </span>
                                  )}
                                  {lead.encuesta.datos_extra?.interes?.toLowerCase() === 'alto' && (
                                    <span className="animate-pulse text-sm" title="Alta Intensidad">🔥</span>
                                  )}
                                </div>
                              ) : lead.encuesta?.tipo_resultados === 'AGENDAMIENTO_CITA' ? (
                                <div className="flex items-center gap-1.5">
                                  <span className="bg-purple-100 text-purple-700 text-[10px] px-2 py-0.5 rounded-full font-bold flex items-center gap-1 border border-purple-200 shadow-sm">
                                    <Calendar size={12} /> {lead.encuesta.datos_extra?.fecha_cita ? t('APPOINTMENT', 'CITA') : t('INTERESTED', 'INTERÉS')}
                                  </span>
                                </div>
                              ) : (
                                <div className="flex gap-1.5">
                                  {['puntuacion_comercial', 'puntuacion_instalador', 'puntuacion_rapidez'].map((key) => {
                                    const raw = (lead as any)[key] ?? (lead.encuesta as any)?.[key];
                                    const num = raw != null && raw !== '' ? Number(raw) : null;
                                    const score = num != null && !Number.isNaN(num) ? num : null;
                                    return (
                                      <div key={key} className={`w-7 h-7 flex items-center justify-center rounded-lg text-xs font-bold shadow-sm transition-transform hover:scale-110 ${getScoreColor(score)}`}>
                                        {score != null ? score : '-'}
                                      </div>
                                    );
                                  })}
                                </div>
                              )}
                              {lead.comentarios && lead.comentarios !== "Sin comentarios" && (
                                <p className="text-[10px] italic text-gray-500 bg-gray-50/50 p-1.5 rounded border border-gray-100 line-clamp-2 max-w-[200px]">
                                  "{lead.comentarios}"
                                </p>
                              )}
                            </div>
                          ) : (
                            <span className="text-gray-400 italic text-xs">
                              {lead.status === 'unreached' ? t('No answer', 'No contestó') :
                                lead.status === 'rejected_opt_out' ? t('Rejected', 'Rechazada') :
                                  lead.status === 'pending' ? t('Waiting...', 'Esperando...') : t('No data', 'Sin datos')}
                            </span>
                          )}

                          {/* Botón de transcripción modal reutilizable */}
                          {(() => {
                            const enc = lead.encuesta;
                            const TERMINAL = ['completed', 'completada', 'failed', 'unreached', 'incomplete', 'rejected_opt_out'];
                            if (!TERMINAL.includes(lead.status) || !enc) return null;
                            return (
                              <button
                                onClick={() => setViewingTranscriptLead(enc)}
                                className={`mt-2 inline-flex items-center gap-1 text-[10px] px-2 py-1 rounded-md font-semibold transition-all shadow-sm
                                          ${enc.transcription
                                    ? 'bg-blue-50 text-blue-700 border border-blue-200 hover:bg-blue-100 hover:shadow'
                                    : 'bg-gray-50 text-gray-400 border border-gray-100 opacity-60'}`}
                              >
                                <FileText size={10} />
                                {t('Transcript', 'Transcripción')}
                              </button>
                            );
                          })()}
                        </td>
                        <td className="px-6 py-4 text-sm text-gray-500">
                          {lead.updated_at ? new Date(lead.updated_at).toLocaleString() : '-'}
                        </td>
                        <td className="px-6 py-4 text-right">
                          {['failed', 'unreached', 'incomplete'].includes(lead.status) && (() => {
                            const maxRetries = (selectedCampaign as any).retries_count || 3;
                            const remaining = Math.max(0, maxRetries - (lead.retries_attempted || 0));
                            return remaining > 0 ? (
                              <button
                                onClick={() => handleRetryLead(lead.id)}
                                className="text-xs bg-white border border-gray-200 hover:bg-gray-50 text-gray-700 px-2 py-1 rounded shadow-sm inline-flex items-center gap-1 transition-all"
                                title={t("Retry this call", "Reintentar esta llamada")}
                              >
                                <Clock className="w-3 h-3 text-blue-500" />
                                {t("Retry", "Reintentar")} ({remaining} {t("remaining", "restantes")})
                              </button>
                            ) : (
                              <span className="text-xs text-gray-400 italic">{t("No retries", "Sin reintentos")}</span>
                            );
                          })()}
                          {lead.status === 'completed' && (
                            <span className="text-xs text-green-600">✓ {t("Completed", "Completada")}</span>
                          )}
                          {lead.status === 'rejected_opt_out' && (
                            <span className="text-xs text-red-600">✗ {t("Rejected", "Rechazada")}</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        )}
        {/* Modal de Transcripción de Lead */}
        <CallResultModal
          result={viewingTranscriptLead}
          onClose={() => setViewingTranscriptLead(null)}
        />
        {renderEditModal()}
      </div>
    );
  }


  // --- Main Campaign List View ---

  if (showCreate) {
    return (
      <div className="max-w-3xl mx-auto space-y-8 pb-12">
        <div className="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
          <div className="px-8 py-6 border-b border-slate-100 flex justify-between items-center bg-slate-50/50">
            <div>
              <h2 className="text-xl font-bold text-slate-900 tracking-tight">{t("Create Campaign", "Crear Campaña")}</h2>
              <p className="text-sm text-slate-500 mt-0.5">{t("Step-by-step wizard", "Asistente paso a paso")}</p>
            </div>
            <button onClick={() => { setShowCreate(false); resetWizard(); }} className="text-slate-400 hover:text-slate-600 p-2 rounded-lg hover:bg-white transition-colors">
              <X className="w-5 h-5" />
            </button>
          </div>

          <div className="px-8 pt-8 pb-2">
            <div className="flex items-center justify-between relative">
              <div className="absolute left-0 right-0 top-5 h-px bg-slate-100 mx-12" aria-hidden />
              {WIZARD_STEPS.map((step, idx) => {
                const Icon = step.icon;
                const active = wizardStep === idx;
                const done = wizardStep > idx;
                return (
                  <button
                    key={step.key}
                    type="button"
                    onClick={() => idx < wizardStep && setWizardStep(idx)}
                    disabled={idx > wizardStep}
                    className="relative flex flex-col items-center gap-2 flex-1 z-10 disabled:cursor-default"
                  >
                    <div className={`w-10 h-10 rounded-full flex items-center justify-center border-2 transition-all duration-300 ${
                      active ? 'bg-slate-900 border-slate-900 text-white shadow-lg shadow-slate-900/20' :
                      done ? 'bg-emerald-500 border-emerald-500 text-white' :
                      'bg-white border-slate-200 text-slate-400'
                    }`}>
                      {done ? <Check className="w-4 h-4" /> : <Icon className="w-4 h-4" />}
                    </div>
                    <span className={`text-xs font-semibold ${active ? 'text-slate-900' : done ? 'text-emerald-700' : 'text-slate-400'}`}>
                      {step.label}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

        <div className="px-8 py-8 space-y-8 min-h-[320px]">
          {error && (
            <div className="p-4 bg-red-50 text-red-600 rounded-xl text-sm flex items-center gap-2">
              <AlertCircle className="w-4 h-4 shrink-0" />
              {error}
            </div>
          )}

          {wizardStep === 0 && (
          <>
          <div>
            <label className="block text-xs font-medium text-slate-500 mb-2">{t("Campaign Name", "Nombre de la Campaña")}</label>
            <input
              type="text"
              className="w-full px-4 py-3 border border-slate-200 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none bg-slate-50/30 focus:bg-white transition-all"
              placeholder={t("e.g. Q1 Customer Survey", "Ej: Encuesta Clientes Q1")}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>

          {isPlatformOwner && (
            <div>
              <label className="block text-xs font-medium text-slate-500 mb-2">{t("Company / Project", "Empresa / Proyecto")}</label>
              <select
                className="w-full px-4 py-3 border border-slate-200 rounded-xl focus:ring-2 focus:ring-indigo-500/20 outline-none bg-white"
                value={selectedEmpresa || ''}
                onChange={(e) => setSelectedEmpresa(e.target.value ? Number(e.target.value) : null)}
              >
                <option value="">-- {t("All Companies", "Todas las Empresas")} -- ({t("Not recommended", "No recomendado")})</option>
                {empresas.map(emp => (
                  <option key={emp.id} value={emp.id}>{emp.nombre}</option>
                ))}
              </select>
            </div>
          )}

          <div>
            <label className="block text-xs font-medium text-slate-500 mb-3">{t("Select Agent", "Selecciona el agente")}</label>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {agents.length === 0 ? (
                <p className="text-sm text-slate-400 col-span-2 py-4 text-center">{t("No agents available", "No hay agentes disponibles")}</p>
              ) : agents.map(a => (
                <button
                  key={a.id}
                  type="button"
                  onClick={() => setSelectedAgent(String(a.id))}
                  className={`flex items-center gap-3 p-4 rounded-xl border text-left transition-all ${
                    String(selectedAgent) === String(a.id)
                      ? 'border-indigo-400 bg-indigo-50/50 ring-2 ring-indigo-500/20 shadow-sm'
                      : 'border-slate-100 bg-white hover:border-slate-200 hover:shadow-sm'
                  }`}
                >
                  <div className={`w-10 h-10 rounded-xl flex items-center justify-center text-sm font-bold shrink-0 ${
                    String(selectedAgent) === String(a.id) ? 'bg-indigo-600 text-white' : 'bg-slate-100 text-slate-600'
                  }`}>
                    {a.name.charAt(0).toUpperCase()}
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-slate-900 truncate">{a.name}</p>
                    <p className="text-xs text-slate-500">{t('Voice agent', 'Agente de voz')}</p>
                  </div>
                  {String(selectedAgent) === String(a.id) && <Check className="w-4 h-4 text-indigo-600 ml-auto shrink-0" />}
                </button>
              ))}
            </div>
          </div>
          </>
          )}

          {wizardStep === 1 && (
          <>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">{t("Data Input Method", "Método de Entrada de Datos")}</label>
            <select
              className="w-full px-4 py-2 border border-gray-200 rounded-lg focus:ring-2 focus:ring-black focus:border-transparent outline-none"
              value={dataSource}
              onChange={(e) => setDataSource(e.target.value as 'csv' | 'api' | 'manual')}
            >
              <option value="csv">{t("CSV File", "Archivo CSV")}</option>
              <option value="manual">{t("Manual Input / Copy-Paste", "Entrada Manual / Copiar-Pegar")}</option>
              <option value="api">{t("API Integration (Developers)", "Integración API (Desarrolladores)")}</option>
            </select>
          </div>

          {dataSource === 'manual' ? (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">{t("Enter Phones (and optional Names)", "Introduce Teléfonos (y Nombres opcionales)")}</label>
              <textarea
                className="w-full px-4 py-2 border border-gray-200 rounded-lg h-32 font-mono text-sm focus:ring-2 focus:ring-black focus:border-transparent outline-none"
                placeholder={"+34600112233, Juan Perez\n+34600445566, Maria"}
                value={manualInput}
                onChange={(e) => setManualInput(e.target.value)}
              />
              <p className="text-xs text-gray-500 mt-1">{t("One record per line. Format: Phone, Name (Name is optional)", "Un registro por línea. Formato: Teléfono, Nombre (El nombre es opcional)")}</p>
            </div>
          ) : dataSource === 'csv' ? (
            <div>
              <label className="block text-xs font-medium text-slate-500 mb-2">{t("CSV File", "Archivo CSV")}</label>
              <div
                className={`relative border-2 border-dashed rounded-2xl p-10 text-center transition-all duration-300 ${
                  csvDragActive ? 'border-indigo-400 bg-indigo-50/30 scale-[1.01]' :
                  csvFile ? 'border-emerald-300 bg-emerald-50/20' :
                  'border-slate-200 bg-slate-50/30 hover:border-slate-300 hover:bg-slate-50/50'
                }`}
                onDragOver={(e) => { e.preventDefault(); setCsvDragActive(true); }}
                onDragLeave={() => setCsvDragActive(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setCsvDragActive(false);
                  const f = e.dataTransfer.files?.[0];
                  if (f?.name.endsWith('.csv')) processCsvFile(f);
                }}
              >
                <input
                  type="file"
                  accept=".csv"
                  className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) processCsvFile(f);
                  }}
                />
                {csvParsing ? (
                  <div className="flex flex-col items-center gap-3">
                    <Loader2 className="w-10 h-10 text-indigo-500 animate-spin" />
                    <p className="text-sm font-medium text-slate-600">{t('Analyzing contacts...', 'Analizando contactos...')}</p>
                  </div>
                ) : (
                  <>
                    <div className={`w-14 h-14 mx-auto mb-4 rounded-2xl flex items-center justify-center ${csvFile ? 'bg-emerald-100' : 'bg-white border border-slate-100 shadow-sm'}`}>
                      {csvFile ? <FileSpreadsheet className="w-7 h-7 text-emerald-600" /> : <Upload className="w-7 h-7 text-slate-400" />}
                    </div>
                    <p className="text-sm font-medium text-slate-700">
                      {csvFile ? csvFile.name : t('Drag & drop your CSV here', 'Arrastra tu CSV aquí')}
                    </p>
                    <p className="text-xs text-slate-400 mt-1">{t('or click to browse · phone, name columns', 'o haz clic · columnas teléfono, nombre')}</p>
                    {csvLeadCount !== null && csvFile && (
                      <div className="mt-5 inline-flex items-center gap-2 px-4 py-2 bg-emerald-100 text-emerald-800 rounded-full text-sm font-semibold">
                        <Check className="w-4 h-4" />
                        {csvLeadCount} {t('valid numbers detected', 'números válidos detectados')}
                      </div>
                    )}
                  </>
                )}
              </div>
              <div className="mt-2 text-right">
                <a
                  href="#"
                  onClick={(e) => {
                    e.preventDefault();
                    const csvContent = "phone,name\n+34600123456,Cliente Ejemplo\n+34600999999,Otro Cliente";
                    const blob = new Blob([csvContent], { type: 'text/csv' });
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = "plantilla_clientes.csv";
                    a.click();
                    window.URL.revokeObjectURL(url);
                  }}
                  className="text-xs text-blue-600 hover:underline flex items-center justify-end gap-1"
                >
                  <Upload className="w-3 h-3" /> {t("Download Template", "Descargar Plantilla")}
                </a>
              </div>
            </div>
          ) : (
            <div className="bg-gray-50 p-4 rounded-lg border border-gray-200">
              <p className="text-sm text-gray-600 mb-2">
                Usa nuestra API para agregar prospectos de forma programática a esta campaña.
              </p>
              <code className="text-xs bg-gray-100 p-2 block rounded overflow-x-auto">
                curl -X POST {API_URL}/api/campaigns/{'{id}'}/leads \
                -H "Content-Type: application/json" \
                -d '{'{ "phone": "+34600000000" }'}'
              </code>
            </div>
          )}
          </>
          )}

          {wizardStep === 2 && (
          <>
          <div>
            <h3 className="text-sm font-semibold text-slate-800 mb-4 flex items-center gap-2">
              <CalendarClock className="w-4 h-4 text-indigo-600" />
              {t("Schedule launch", "Programar lanzamiento")}
            </h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4">
              <button
                type="button"
                onClick={() => { setScheduleMode('now'); setScheduledTime(''); }}
                className={`p-4 rounded-xl border text-left transition-all ${
                  scheduleMode === 'now' ? 'border-indigo-400 bg-indigo-50/50 ring-2 ring-indigo-500/15' : 'border-slate-100 hover:border-slate-200'
                }`}
              >
                <Zap className={`w-5 h-5 mb-2 ${scheduleMode === 'now' ? 'text-indigo-600' : 'text-slate-400'}`} />
                <p className="text-sm font-semibold text-slate-900">{t('Launch immediately', 'Lanzar de inmediato')}</p>
                <p className="text-xs text-slate-500 mt-0.5">{t('Campaign starts as soon as you confirm', 'La campaña arranca al confirmar')}</p>
              </button>
              <button
                type="button"
                onClick={() => setScheduleMode('later')}
                className={`p-4 rounded-xl border text-left transition-all ${
                  scheduleMode === 'later' ? 'border-indigo-400 bg-indigo-50/50 ring-2 ring-indigo-500/15' : 'border-slate-100 hover:border-slate-200'
                }`}
              >
                <CalendarClock className={`w-5 h-5 mb-2 ${scheduleMode === 'later' ? 'text-indigo-600' : 'text-slate-400'}`} />
                <p className="text-sm font-semibold text-slate-900">{t('Schedule date & time', 'Programar fecha y hora')}</p>
                <p className="text-xs text-slate-500 mt-0.5">{t('Pick when calls should begin', 'Elige cuándo deben empezar las llamadas')}</p>
              </button>
            </div>
            {scheduleMode === 'later' && (
              <input
                type="datetime-local"
                className="w-full px-4 py-3 border border-slate-200 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none bg-slate-50/30 focus:bg-white"
                value={scheduledTime}
                onChange={(e) => setScheduledTime(e.target.value)}
              />
            )}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">{t("Retry Interval", "Intervalo de Reintento")}</label>
              <div className="flex gap-2">
                <input
                  type="number"
                  min="1"
                  className="flex-1 px-4 py-2.5 border border-gray-200 rounded-xl outline-none focus:ring-2 focus:ring-blue-500/20"
                  value={retryInterval}
                  onChange={(e) => setRetryInterval(Number(e.target.value))}
                />
                <select
                  value={retryUnit}
                  onChange={(e) => setRetryUnit(e.target.value as 'minutes' | 'hours' | 'days')}
                  className="w-1/3 px-3 py-2.5 border border-gray-200 rounded-xl outline-none bg-white"
                >
                  <option value="minutes">{t("Minutes", "Minutos")}</option>
                  <option value="hours">{t("Hours", "Horas")}</option>
                  <option value="days">{t("Days", "Dias")}</option>
                </select>
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">{t("Number of Retries", "Número de Reintentos")}</label>
              <input
                type="number"
                min="0"
                max="10"
                className="w-full px-4 py-2.5 border border-gray-200 rounded-xl outline-none focus:ring-2 focus:ring-blue-500/20"
                value={retriesCount}
                onChange={(e) => setRetriesCount(Number(e.target.value))}
              />
            </div>
            <div className="md:col-span-2">
              <label className="block text-sm font-medium text-gray-700 mb-2">{t("Drip Interval (Minutes)", "Intervalo entre llamadas (min)")}</label>
              <input
                type="number"
                min="1"
                className="w-full px-4 py-2.5 border border-gray-200 rounded-xl outline-none focus:ring-2 focus:ring-blue-500/20"
                value={intervalMinutes}
                onChange={(e) => setIntervalMinutes(Number(e.target.value))}
              />
            </div>
          </div>

          <div className="border-t border-gray-100 pt-6">
            <h3 className="text-sm font-medium text-gray-700 mb-1">{t("Dynamic Data Extraction", "Extracción de Datos Dinámica")}</h3>
            <p className="text-xs text-gray-500 mb-4">{t("Define what information the AI should extract from the conversation.", "Define qué información debe extraer la IA de la conversación.")}</p>
            <div className="space-y-3">
              {extractionSchema.map((field, index) => (
                <div key={index} className="flex flex-col md:flex-row gap-2 bg-gray-50 p-3 rounded-lg border border-gray-200 items-start md:items-center">
                  <div className="flex-1 w-full relative">
                    <label className="text-[10px] uppercase text-gray-500 font-semibold absolute -top-2 bg-gray-50 px-1 left-2">Variable Key</label>
                    <input type="text" placeholder="ej: opcion_cliente" className="w-full text-xs px-3 py-2 border border-gray-300 rounded focus:border-blue-500 outline-none bg-white" value={field.key} onChange={(e) => {
                      const newSchema = [...extractionSchema];
                      newSchema[index].key = e.target.value.replace(/\s+/g, '_').toLowerCase();
                      setExtractionSchema(newSchema);
                    }} />
                  </div>
                  <div className="flex-1 w-full relative">
                    <label className="text-[10px] uppercase text-gray-500 font-semibold absolute -top-2 bg-gray-50 px-1 left-2">Display Name</label>
                    <input type="text" placeholder="ej: Opción del Cliente" className="w-full text-xs px-3 py-2 border border-gray-300 rounded focus:border-blue-500 outline-none bg-white" value={field.label} onChange={(e) => {
                      const newSchema = [...extractionSchema];
                      newSchema[index].label = e.target.value;
                      setExtractionSchema(newSchema);
                    }} />
                  </div>
                  <div className="w-full md:w-32 relative">
                    <label className="text-[10px] uppercase text-gray-500 font-semibold absolute -top-2 bg-gray-50 px-1 left-2">Type</label>
                    <select className="w-full text-xs px-3 py-2 border border-gray-300 rounded focus:border-blue-500 outline-none bg-white font-medium" value={field.type} onChange={(e) => {
                      const newSchema = [...extractionSchema];
                      newSchema[index].type = e.target.value;
                      if(e.target.value !== 'enum') delete newSchema[index].options;
                      else newSchema[index].options = [];
                      setExtractionSchema(newSchema);
                    }}>
                      <option value="text">Texto</option>
                      <option value="number">Número</option>
                      <option value="boolean">Verdadero/Falso</option>
                      <option value="enum">Opciones (Enum)</option>
                    </select>
                  </div>
                  {field.type === 'enum' && (
                    <div className="flex-1 w-full relative">
                      <label className="text-[10px] uppercase text-gray-500 font-semibold absolute -top-2 bg-gray-50 px-1 left-2">Opciones (,)</label>
                      <input type="text" placeholder="opcion1, opcion2..." className="w-full text-xs px-3 py-2 border border-blue-200 rounded focus:border-blue-500 outline-none bg-blue-50" value={field.options?.join(', ') || ''} onChange={(e) => {
                        const newSchema = [...extractionSchema];
                        newSchema[index].options = e.target.value.split(',').map(s=>s.trim()).filter(Boolean);
                        setExtractionSchema(newSchema);
                      }} />
                    </div>
                  )}
                  <button onClick={() => setExtractionSchema(extractionSchema.filter((_, i) => i !== index))} className="p-2 text-red-500 hover:bg-red-100 rounded border border-transparent hover:border-red-200 transition-colors mt-2 md:mt-0">
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              ))}
              <div className="flex">
                <button onClick={() => setExtractionSchema([...extractionSchema, {key: '', label: '', type: 'text'}])} className="text-xs bg-white text-blue-600 px-3 py-2 rounded-lg border border-dashed border-blue-300 hover:bg-blue-50 flex items-center gap-1 font-medium transition-all shadow-sm">
                  <Plus className="w-3 h-3" /> {t("Add Custom Extraction Field", "Añadir campo a extraer")}
                </button>
              </div>
            </div>
          </div>
          </>
          )}
        </div>

        <div className="px-8 py-6 bg-gray-50/80 border-t border-gray-100 flex justify-between items-center gap-3">
          <button
            type="button"
            onClick={() => { setShowCreate(false); resetWizard(); }}
            className="px-5 py-2.5 text-gray-600 font-medium hover:bg-gray-100 rounded-xl transition-colors"
          >
            {t("Cancel", "Cancelar")}
          </button>
          <div className="flex gap-3">
            {wizardStep > 0 && (
              <button
                type="button"
                onClick={() => setWizardStep((s) => s - 1)}
                className="px-5 py-2.5 border border-gray-200 text-gray-700 font-medium rounded-xl hover:bg-white flex items-center gap-1 transition-all"
              >
                <ChevronLeft className="w-4 h-4" />
                {t("Back", "Atrás")}
              </button>
            )}
            {wizardStep < 2 ? (
              <button
                type="button"
                disabled={!canWizardNext()}
                onClick={() => setWizardStep((s) => s + 1)}
                className="px-6 py-2.5 bg-blue-600 text-white font-semibold rounded-xl hover:bg-blue-500 flex items-center gap-1 disabled:opacity-40 shadow-md shadow-blue-500/20 transition-all"
              >
                {t("Next", "Siguiente")}
                <ChevronRight className="w-4 h-4" />
              </button>
            ) : (
              <button
                type="button"
                onClick={handleCreate}
                disabled={loading || !canWizardNext()}
                className="px-6 py-2.5 bg-blue-600 text-white font-semibold rounded-xl hover:bg-blue-500 flex items-center gap-2 disabled:opacity-40 shadow-md shadow-blue-500/20 transition-all min-w-[160px] justify-center"
              >
                {loading ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    {t('Saving...', 'Guardando...')}
                  </>
                ) : (
                  t('Launch Campaign', 'Lanzar Campaña')
                )}
              </button>
            )}
          </div>
        </div>
        </div>

        {/* Campaigns table below wizard */}
        <div className="bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-100">
            <h3 className="font-bold text-gray-900">{t("Current campaigns", "Campañas actuales")}</h3>
          </div>
          {campaigns.length === 0 ? (
            <p className="px-6 py-10 text-center text-gray-400 text-sm">{t("No campaigns yet", "Aún no hay campañas")}</p>
          ) : (
            <table className="w-full text-left">
              <thead className="bg-gray-50 border-b border-gray-100">
                <tr>
                  <th className="px-6 py-3 text-xs font-semibold text-gray-500 uppercase">{t("Name", "Nombre")}</th>
                  <th className="px-6 py-3 text-xs font-semibold text-gray-500 uppercase">{t("Status", "Estado")}</th>
                  <th className="px-6 py-3 text-xs font-semibold text-gray-500 uppercase text-right">{t("Scheduled", "Programada")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {campaigns.slice(0, 8).map((c) => (
                  <tr key={c.id} className="hover:bg-gray-50/80 transition-colors">
                    <td className="px-6 py-3 text-sm font-medium text-gray-900">{c.name}</td>
                    <td className="px-6 py-3"><StatusBadge status={c.status} /></td>
                    <td className="px-6 py-3 text-sm text-gray-500 text-right font-mono">
                      {c.scheduled_time ? new Date(c.scheduled_time).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' }) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">{t("Campaigns", "Campañas")}</h1>
          <p className="text-gray-500">{t("Manage your bulk outbound call campaigns", "Gestiona tus campañas de llamadas salientes masivas")}</p>
        </div>
        <button
          onClick={() => { resetWizard(); setShowCreate(true); }}
          className="flex items-center gap-2 px-5 py-2.5 bg-blue-600 text-white rounded-xl hover:bg-blue-500 shadow-md shadow-blue-500/20 font-semibold transition-all"
        >
          <Plus className="w-4 h-4" />
          {t("Create Campaign", "Crear Campaña")}
        </button>
      </div>

      {listLoading ? (
        <div className="flex justify-center py-16">
          <Loader2 className="w-10 h-10 animate-spin text-blue-500" />
        </div>
      ) : (
      <div className="space-y-8">
        {empresas.length === 0 && campaigns.length === 0 ? (
          <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-12 text-center text-gray-500">
            {t("No companies or campaigns found.", "No se encontraron empresas ni campañas.")}
          </div>
        ) : (
          empresas.map((empresa) => {
            const companyCampaigns = campaigns.filter(c => c.empresa_id === empresa.id);
            return (
              <div key={empresa.id} className="space-y-3">
                <div className="flex items-center justify-between px-1">
                  <div className="flex items-center gap-2">
                    <Building2 className="w-5 h-5 text-blue-600" />
                    <h2 className="text-lg font-bold text-gray-800 uppercase tracking-wider">{empresa.nombre}</h2>
                    <span className="text-xs font-medium text-gray-400 bg-gray-50 px-2 py-0.5 rounded-full border border-gray-100">
                      {companyCampaigns.length} {companyCampaigns.length === 1 ? t("Campaña", "Campaña") : t("Campañas", "Campañas")}
                    </span>
                  </div>
                  <button
                    onClick={() => handleCreateNewForCompany(empresa.id)}
                    className="flex items-center gap-1 px-3 py-1 bg-blue-50 text-blue-700 rounded-lg hover:bg-blue-100 transition-colors text-xs font-semibold"
                  >
                    <Plus className="w-3 h-3" />
                    {t("New Campaign", "Nueva Campaña")}
                  </button>
                </div>

                <div className="h-px bg-gray-100 mb-4"></div>

                {companyCampaigns.length === 0 ? (
                  <div className="bg-slate-900/40 backdrop-blur-xl rounded-2xl border border-dashed border-cyan-500/20 p-12 text-center flex flex-col items-center gap-6 group hover:border-cyan-500/40 transition-all duration-500">
                    <div className="relative w-24 h-24 flex items-center justify-center">
                      {/* Radar Animation SVG */}
                      <svg className="absolute inset-0 w-full h-full text-cyan-500/20 animate-[spin_4s_linear_infinite]" viewBox="0 0 100 100">
                        <circle cx="50" cy="50" r="48" fill="none" stroke="currentColor" strokeWidth="0.5" strokeDasharray="4 4" />
                        <circle cx="50" cy="50" r="30" fill="none" stroke="currentColor" strokeWidth="0.5" />
                        <line x1="50" y1="50" x2="50" y2="2" stroke="currentColor" strokeWidth="1" strokeLinecap="round" />
                      </svg>
                      <div className="absolute inset-0 bg-cyan-500/5 rounded-full animate-pulse" />
                      <Target className="w-10 h-10 text-cyan-500/40 group-hover:text-cyan-400 transition-colors" />
                    </div>
                    <div>
                      <p className="text-slate-200 font-bold tracking-tight uppercase">{t("No active signals detected", "No se detectan señales activas")}</p>
                      <p className="text-slate-500 text-xs mt-1 max-w-[200px] mx-auto">{t("Launch a new campaign to begin intercepting customer signals.", "Inicia una nueva campaña para interceptar señales de clientes.")}</p>
                    </div>
                    <button
                      onClick={() => handleCreateNewForCompany(empresa.id)}
                      className="px-6 py-2 bg-cyan-500/10 hover:bg-cyan-500/20 text-cyan-400 text-xs font-bold rounded-xl border border-cyan-500/30 transition-all uppercase tracking-widest"
                    >
                      {t("Initialize Campaign", "Inicializar Campaña")}
                    </button>
                  </div>
                ) : (
                  <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
                    <table className="w-full text-left">
                      <thead className="bg-gray-50 border-b border-gray-100">
                        <tr>
                          <th className="px-6 py-4 text-xs font-semibold text-gray-500 uppercase tracking-wider">{t("Campaign Name", "Nombre de la Campaña")}</th>
                          <th className="px-6 py-4 text-xs font-semibold text-gray-500 uppercase tracking-wider">{t("Status", "Estado")}</th>
                          <th className="px-6 py-4 text-xs font-semibold text-gray-500 uppercase tracking-wider">{t("Progress", "Progreso")}</th>
                          <th className="px-6 py-4 text-xs font-semibold text-gray-500 uppercase tracking-wider text-center">{t("Scheduled", "Planificado")}</th>
                          <th className="px-6 py-4 text-right text-xs font-semibold text-gray-500 uppercase tracking-wider">{t("Actions", "Acciones")}</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-100">
                        {companyCampaigns.map((campaign) => (
                          <tr key={campaign.id} className="hover:bg-gray-50 transition-colors cursor-pointer" onClick={() => loadCampaignDetails(campaign)}>
                            <td className="px-6 py-4 text-sm font-medium text-gray-900">{campaign.name}</td>
                            <td className="px-6 py-4">
                              <StatusBadge status={campaign.status} />
                            </td>
                            <td className="px-6 py-4" onClick={(e) => e.stopPropagation()}>
                              <CampaignProgressBar
                                called={campaign.called_leads || 0}
                                total={campaign.total_leads || 0}
                              />
                            </td>
                            <td className="px-6 py-4 text-sm text-gray-500 font-mono text-center">
                              {campaign.scheduled_time ? new Date(campaign.scheduled_time).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' }) : '-'}
                            </td>
                            <td className="px-6 py-4 text-right text-sm font-medium" onClick={(e) => e.stopPropagation()}>
                              <div className="flex justify-end gap-2">
                                <button
                                  onClick={() => openEditModal(campaign)}
                                  className="p-1.5 text-blue-600 hover:bg-blue-50 rounded-lg transition-colors"
                                  title="Edit Campaign"
                                >
                                  <Edit2 className="w-4 h-4" />
                                </button>
                                <button
                                  onClick={() => {
                                    if (window.confirm(t('Delete campaign?', '¿Eliminar campaña?'))) {
                                      handleDelete(campaign.id);
                                    }
                                  }}
                                  className="p-1.5 text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                                  title="Delete Campaign"
                                >
                                  <Trash2 className="w-4 h-4" />
                                </button>
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            );
          })
        )}

        {/* Handle campaigns without company assigned (if any) */}
        {(() => {
          const orphaned = campaigns.filter(c => !c.empresa_id || !empresas.find(e => e.id === c.empresa_id));
          if (orphaned.length === 0) return null;
          return (
            <div className="space-y-3 mt-10 opacity-60">
              <div className="flex items-center gap-2 px-1">
                <h2 className="text-lg font-bold text-gray-500 uppercase tracking-wider italic">{t("Orphaned Campaigns (No Company)", "Campañas Huérfanas (Sin Empresa)")}</h2>
              </div>
              <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
                <table className="w-full text-left">
                  <tbody className="divide-y divide-gray-100">
                    {orphaned.map((campaign) => (
                      <tr key={campaign.id} className="hover:bg-gray-50 transition-colors cursor-pointer" onClick={() => loadCampaignDetails(campaign)}>
                        <td className="px-6 py-4 text-sm font-medium text-gray-900">{campaign.name}</td>
                        <td className="px-6 py-4 text-right">
                          <StatusBadge status={campaign.status} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          );
        })()}
      </div>
      )}
      {renderEditModal()}
    </div>
  );
}
