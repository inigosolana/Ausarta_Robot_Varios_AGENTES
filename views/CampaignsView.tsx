import React, { useState, useEffect } from 'react';
import {
  Plus, Upload, Clock, AlertCircle, History, Trash2, X, Edit2, Building2
} from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { useTranslation } from 'react-i18next';
import { supabase } from '../lib/supabase';
import type { Empresa } from '../types';
import DashboardView from './DashboardView';
import ResultsView from './ResultsView';

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
  is_question_based?: boolean;
  empresas?: { nombre: string };
}

interface Lead {
  id: number;
  phone_number: string;
  status: string; // pending, called, failed
  updated_at?: string;
  puntuacion_comercial?: number;
  puntuacion_instalador?: number;
  puntuacion_rapidez?: number;
  comentarios?: string;
  transcription_preview?: string;
  retries_attempted?: number;
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
  const [agents, setAgents] = useState<Agent[]>([]);
  const [empresas, setEmpresas] = useState<Empresa[]>([]);
  const [selectedEmpresa, setSelectedEmpresa] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
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
  };

  const handleUpdateCampaign = async () => {
    if (!editingCampaign) return;
    try {
      const payload = {
        name: editName,
        scheduled_time: editTime ? new Date(editTime).toISOString() : null,
        retry_interval: editRetryInterval,
        retry_unit: editRetryUnit,
        retries_count: editRetriesCount
      };
      const res = await fetch(`${API_URL}/api/campaigns/${editingCampaign.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (res.ok) {
        alert(t("Campaign updated!", "¡Campaña actualizada!"));
        setEditingCampaign(null);
        loadCampaigns();
        if (selectedCampaign && selectedCampaign.id === editingCampaign.id) {
          // Reload details if we are viewing the edited campaign
          const updatedCamp = await (await fetch(`${API_URL}/api/campaigns/${editingCampaign.id}`)).json();
          setSelectedCampaign(updatedCamp.campaign);
        }
      } else {
        alert(t("Update failed", "Error al actualizar"));
      }
    } catch (e) {
      alert(t("Error updating campaign", "Error al actualizar la campaña"));
    }
  };

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

  const API_URL = import.meta.env.VITE_API_URL || window.location.origin;

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
  }, [profile, isPlatformOwner]);

  useEffect(() => {
    loadAgents();
  }, [profile, isPlatformOwner, selectedEmpresa]);

  const loadEmpresas = async () => {
    try {
      const resp = await fetch(`${API_URL}/api/empresas`);
      if (resp.ok) {
        const data = await resp.json();
        // data here is a list of all companies
        let filtered = data;

        // If not platform owner, restrict to their own company
        if (!isPlatformOwner && profile?.empresa_id) {
          filtered = data.filter((e: Empresa) => e.id === profile.empresa_id);
        }

        setEmpresas(Array.isArray(filtered) ? filtered : []);
      }
    } catch (e) {
      console.error("Error loading empresas from API:", e);
      // Fallback to Supabase direct if API fails
      try {
        let query = supabase.from('empresas').select('*').order('nombre');
        if (!isPlatformOwner && profile?.empresa_id) {
          query = query.eq('id', profile.empresa_id);
        }
        const { data } = await query;
        if (data) setEmpresas(data);
      } catch (e2) {
        console.error("Fallback loadEmpresas failed:", e2);
      }
    }
  };

  const loadAgents = async () => {
    try {
      let url = `${API_URL}/api/agents`;
      if (profile && !isPlatformOwner && profile.empresa_id) {
        url += `?empresa_id=${profile.empresa_id}`;
      } else if (isPlatformOwner && selectedEmpresa) {
        url += `?empresa_id=${selectedEmpresa}`;
      }
      const res = await fetch(url);
      if (res.ok) {
        const data = await res.json();
        setAgents(Array.isArray(data) ? data : []);
        // Auto-select first agent if available and selected agent is not in the list
        if (Array.isArray(data) && data.length > 0) {
          setSelectedAgent(data[0].id);
        } else {
          setSelectedAgent('');
        }
      }
    } catch (e) {
      console.error("Error loading agents:", e);
      setAgents([]);
    }
  };

  const loadCampaigns = async () => {
    try {
      let url = `${API_URL}/api/campaigns`;
      if (profile && !isPlatformOwner && profile.empresa_id) {
        url += `?empresa_id=${profile.empresa_id}`;
      }
      const res = await fetch(url);
      if (res.ok) {
        const data = await res.json();
        setCampaigns(Array.isArray(data) ? data : []);
      } else {
        setCampaigns([]);
      }
    } catch (e) {
      console.error("Error loading campaigns:", e);
      setCampaigns([]);
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
      alert(t("Error loading details", "Error al cargar detalles"));
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
    setShowCreate(true);
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
          scheduled_time: scheduledTime ? new Date(scheduledTime).toISOString() : null,
          status: 'pending',
          retry_interval: retryInterval || 60,
          retry_unit: retryUnit,
          retries_count: retriesCount
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
      loadCampaigns();
      alert(t('Campaign created successfully!', '¡Campaña creada exitosamente!'));

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
      alert(t("Error deleting campaign", "Error al eliminar la campaña"));
    }
  };

  const handleRetryFailed = async (id: number) => {
    if (!confirm(t("Are you sure you want to retry all failed calls in this campaign?", "¿Estás seguro de que quieres reintentar todas las llamadas fallidas en esta campaña?"))) return;
    try {
      const res = await fetch(`${API_URL}/api/campaigns/${id}/retry`, { method: 'POST' });
      const data = await res.json();

      if (res.ok && data.status === 'success') {
        alert(t(`Successfully queued ${data.retried_count} failed calls for retry.`, `Se han encolado exitosamente ${data.retried_count} llamadas fallidas para reintento.`));
        if (selectedCampaign) loadCampaignDetails(selectedCampaign);
        loadCampaigns();
      } else {
        alert(t("Failed to retry calls.", "Error al reintentar llamadas."));
      }
    } catch (e) {
      alert(t("Error connecting to server", "Error al conectar con el servidor"));
    }
  };

  const handleRetryLead = async (leadId: number) => {
    try {
      // Usamos endpoint ad-hoc o simplemente forzamos el status a pending
      // Como no hay endpoint específico de retry-single, reusamos la lógica de campañas o creamos uno.
      // Opción rápida: Endpoint update lead. No existe. 
      // Opción B: Crear endpoint en API.py para resetear 1 lead.
      // Opción C (Temporal): Usar el de campaña global pero eso resetea todos los failed.
      // Mejor: implemento una llamada directa a API para updatear el lead a pending.
      // Pero no tengo endpoint exposed.
      // SOLUCIÓN: Agrego endpoint rápido en api.py o asumo que el usuario usará el global.
      // User asked: "que le de manualmente". Wait, I should add the endpoint to api.py first? 
      // I'll assume I can add a small endpoint or use a SQL injection? No.
      // Let's stick to displaying info first. I'll add the UI first.
      const res = await fetch(`${API_URL}/api/campaigns/leads/${leadId}/retry`, { method: 'POST' });
      if (res.ok) {
        // Optimistic update
        setCampaignLeads(prev => prev.map(l =>
          l.id === leadId ? { ...l, status: 'pending', retries_attempted: 0 } : l
        ));
        alert(t("Lead requeued successfully!", "Lead encolado exitosamente!"));
      } else {
        alert(t("Failed to retry lead", "Error al reintentar lead"));
      }
    } catch (e) {
      alert(t("Error connecting to server", "Error al conectar con el servidor"));
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
      pending: 'bg-yellow-100 text-yellow-800',
      running: 'bg-blue-100 text-blue-800',
      completed: 'bg-green-100 text-green-800',
      paused: 'bg-gray-100 text-gray-800',
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
                          {selectedCampaign?.is_question_based ? (
                            lead.comentarios ? (
                              <div className="space-y-1">
                                <div className="font-semibold text-gray-800 text-xs uppercase mb-1">{t("Recorded Responses", "Respuestas Registradas")}:</div>
                                <p className="text-sm text-gray-700 whitespace-pre-wrap bg-gray-50 p-2 rounded border border-gray-100">{lead.comentarios}</p>
                              </div>
                            ) : (
                              <span className="text-gray-400 italic">
                                {lead.status === 'unreached' ? t('No answer', 'No contestó') :
                                  lead.status === 'rejected_opt_out' ? t('Customer refused to answer', 'Cliente rechazó responder') :
                                    lead.status === 'pending' ? t('Waiting...', 'Esperando...') : t('No responses yet', 'Sin respuestas todavía')}
                              </span>
                            )
                          ) : (lead.puntuacion_comercial != null || lead.puntuacion_instalador != null || lead.puntuacion_rapidez != null) ? (
                            <div className="space-y-1">
                              <div className="flex gap-2">
                                <span className="font-bold text-gray-900">C:</span>{lead.puntuacion_comercial ?? '-'}
                                <span className="font-bold text-gray-900">I:</span>{lead.puntuacion_instalador ?? '-'}
                                <span className="font-bold text-gray-900">R:</span>{lead.puntuacion_rapidez ?? '-'}
                              </div>
                              {lead.comentarios && (
                                <p className="text-xs italic text-gray-500 border-l-2 border-gray-200 pl-2">"{lead.comentarios}"</p>
                              )}
                            </div>
                          ) : (
                            <span className="text-gray-400 italic">
                              {lead.status === 'unreached' ? t('No answer', 'No contestó') :
                                lead.status === 'rejected_opt_out' ? t('Customer rejected the survey', 'Cliente rechazó la encuesta') :
                                  lead.status === 'pending' ? t('Waiting...', 'Esperando...') : t('No data yet', 'Sin datos todavía')}
                            </span>
                          )}

                          {/* Transcription Preview (Collapsible better, but inline for now) */}
                          {lead.transcription_preview && (
                            <details className="mt-1">
                              <summary className="text-xs text-blue-500 cursor-pointer hover:underline">{t("View Transcription", "Ver Transcripción")}</summary>
                              <p className="text-xs text-gray-500 mt-1 p-2 bg-gray-50 rounded whitespace-pre-wrap max-h-32 overflow-y-auto">
                                {lead.transcription_preview}
                              </p>
                            </details>
                          )}
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
        {renderEditModal()}
      </div>
    );
  }

  // --- Main Campaign List View ---

  if (showCreate) {
    return (
      <div className="max-w-2xl mx-auto bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
        <div className="p-6 border-b border-gray-100 flex justify-between items-center">
          <h2 className="text-xl font-bold">{t("Create Campaign", "Crear Campaña")}</h2>
          <button onClick={() => setShowCreate(false)} className="text-gray-400 hover:text-gray-600">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-6 space-y-6">
          {error && (
            <div className="p-4 bg-red-50 text-red-600 rounded-lg text-sm flex items-center gap-2">
              <AlertCircle className="w-4 h-4" />
              {error}
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">{t("Campaign Name", "Nombre de la Campaña")}</label>
            <input
              type="text"
              className="w-full px-4 py-2 border border-gray-200 rounded-lg focus:ring-2 focus:ring-black focus:border-transparent outline-none"
              placeholder={t("e.g. Q1 Customer Survey", "Ej: Encuesta Clientes Q1")}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>

          {isPlatformOwner && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">{t("Company / Project", "Empresa / Proyecto")}</label>
              <select
                className="w-full px-4 py-2 border border-gray-200 rounded-lg focus:ring-2 focus:ring-black focus:border-transparent outline-none bg-white"
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
            <label className="block text-sm font-medium text-gray-700 mb-2">{t("Agent", "Agente")}</label>
            <select
              className="w-full px-4 py-2 border border-gray-200 rounded-lg focus:ring-2 focus:ring-black focus:border-transparent outline-none"
              value={selectedAgent}
              onChange={(e) => setSelectedAgent(e.target.value)}
            >
              <option value="">{t("Select an agent", "Selecciona un agente")}</option>
              {agents.map(a => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
          </div>

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
              <label className="block text-sm font-medium text-gray-700 mb-2">{t("CSV File", "Archivo CSV")}</label>
              <div className="border-2 border-dashed border-gray-200 rounded-lg p-8 text-center hover:border-black transition-colors cursor-pointer relative">
                <input
                  type="file"
                  accept=".csv"
                  className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                  onChange={(e) => setCsvFile(e.target.files?.[0] || null)}
                />
                <Upload className="w-8 h-8 text-gray-400 mx-auto mb-2" />
                <p className="text-sm text-gray-600">
                  {csvFile ? csvFile.name : t('Click to upload or drag and drop', 'Haz clic para subir o arrastra y suelta')}
                </p>
                <p className="text-xs text-gray-400 mt-1">{t("Only .csv files", "Solo archivos .csv")}</p>
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

          <div className="border-t border-gray-100 pt-6">
            <button className="flex items-center justify-between w-full text-left font-medium text-gray-700">
              <span>{t("Advanced Settings / Scheduling", "Ajustes Avanzados / Programación")}</span>
              <Clock className="w-4 h-4" />
            </button>
            <div className="mt-4">
              <label className="block text-sm font-medium text-gray-700 mb-2">{t("Scheduled Start Time (Optional)", "Hora de Inicio Programada (Opcional)")}</label>
              <input
                type="datetime-local"
                className="w-full px-4 py-2 border border-gray-200 rounded-lg"
                value={scheduledTime}
                onChange={(e) => setScheduledTime(e.target.value)}
              />
              <p className="text-xs text-gray-500 mt-1">{t("Leave blank to start immediately.", "Dejar en blanco para empezar inmediatamente.")}</p>
            </div>

            <div className="mt-4">
              <label className="block text-sm font-medium text-gray-700 mb-2">{t("Retry Interval", "Intervalo de Reintento")}</label>
              <div className="flex gap-2">
                <input
                  type="number"
                  min="1"
                  className="flex-1 px-4 py-2 border border-gray-200 rounded-lg focus:ring-2 focus:ring-black outline-none"
                  value={retryInterval}
                  onChange={(e) => setRetryInterval(Number(e.target.value))}
                  placeholder={t("Default: 60", "Por defecto: 60")}
                />
                <select
                  value={retryUnit}
                  onChange={(e) => setRetryUnit(e.target.value as any)}
                  className="w-1/3 px-4 py-2 border border-gray-200 rounded-lg focus:ring-2 focus:ring-black outline-none bg-white"
                >
                  <option value="minutes">{t("Minutes", "Minutos")}</option>
                  <option value="hours">{t("Hours", "Horas")}</option>
                  <option value="days">{t("Days", "Dias")}</option>
                </select>
              </div>
              <p className="text-xs text-gray-500 mt-1">{t("Wait time before retrying a failed call.", "Tiempo de espera antes de reintentar una llamada fallida.")}</p>
            </div>

            <div className="mt-4">
              <label className="block text-sm font-medium text-gray-700 mb-2">{t("Number of Retries", "Número de Reintentos")}</label>
              <input
                type="number"
                min="0"
                max="10"
                className="w-full px-4 py-2 border border-gray-200 rounded-lg focus:ring-2 focus:ring-black outline-none"
                value={retriesCount}
                onChange={(e) => setRetriesCount(Number(e.target.value))}
              />
              <p className="text-xs text-gray-500 mt-1">{t("Max number of automatic retries (0 to 10).", "Número máximo de reintentos automáticos (0 a 10).")}</p>
            </div>
          </div>
        </div>

        <div className="p-6 bg-gray-50 border-t border-gray-100 flex justify-end gap-3">
          <button
            onClick={() => setShowCreate(false)}
            className="px-4 py-2 text-gray-700 font-medium hover:bg-gray-100 rounded-lg transition-colors"
          >
            {t("Cancel", "Cancelar")}
          </button>
          <button
            onClick={handleCreate}
            disabled={loading}
            className="px-4 py-2 bg-black text-white font-medium rounded-lg hover:bg-gray-800 transition-colors flex items-center gap-2 disabled:opacity-50"
          >
            {loading ? t('Creating...', 'Creando...') : t('Launch Campaign', 'Lanzar Campaña')}
          </button>
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
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 px-4 py-2 bg-black text-white rounded-lg hover:bg-gray-800 transition-colors"
        >
          <Plus className="w-4 h-4" />
          {t("Create Campaign", "Crear Campaña")}
        </button>
      </div>

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
                  <div className="bg-gray-50 rounded-xl border border-gray-100 p-8 text-center text-gray-400 flex flex-col items-center gap-2">
                    <History className="w-8 h-8 opacity-20" />
                    <p className="text-sm">{t("No campaigns for this company yet.", "Aún no hay campañas para esta empresa.")}</p>
                    <button
                      onClick={() => handleCreateNewForCompany(empresa.id)}
                      className="text-blue-600 text-xs font-medium hover:underline"
                    >
                      {t("Create the first one", "Crea la primera")}
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
                            <td className="px-6 py-4 w-48">
                              <div className="flex flex-col gap-1">
                                <div className="h-2 w-full bg-gray-100 rounded-full overflow-hidden">
                                  <div
                                    className="h-full bg-green-500"
                                    style={{ width: `${Math.min(100, ((campaign.called_leads || 0) / (campaign.total_leads || 1)) * 100)}%` }}
                                  />
                                </div>
                                <div className="text-xs text-gray-500">
                                  {campaign.called_leads || 0} / {campaign.total_leads || 0} {t("calls", "llamadas")}
                                </div>
                              </div>
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
      {renderEditModal()}
    </div>
  );
}
