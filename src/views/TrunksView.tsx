import React, { useEffect, useMemo, useState } from 'react';
import { Building2, Route, Save, RefreshCw } from 'lucide-react';
import { apiFetch } from '../lib/apiFetch';
import { useAuth } from '../contexts/AuthContext';

type EmpresaRow = {
  id: number;
  nombre: string;
  sip_outbound_trunk_id?: string | null;
  sip_inbound_trunk_id?: string | null;
};

const TrunksView: React.FC = () => {
  const { profile } = useAuth();
  const [rows, setRows] = useState<EmpresaRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedEmpresaId, setSelectedEmpresaId] = useState<number | null>(null);
  const [outbound, setOutbound] = useState('');
  const [inbound, setInbound] = useState('');
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const isSuperadmin = profile?.role === 'superadmin';

  const selected = useMemo(
    () => rows.find(r => r.id === selectedEmpresaId) || null,
    [rows, selectedEmpresaId],
  );

  const loadEmpresas = async () => {
    setLoading(true);
    setMsg(null);
    try {
      const res = await apiFetch('/api/admin/empresas');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: EmpresaRow[] = await res.json();
      setRows(data || []);
      if (data?.length && !selectedEmpresaId) {
        setSelectedEmpresaId(data[0].id);
        setOutbound(data[0].sip_outbound_trunk_id || '');
        setInbound(data[0].sip_inbound_trunk_id || '');
      }
    } catch (err: any) {
      setMsg({ ok: false, text: err?.message || 'No se pudieron cargar las empresas' });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadEmpresas();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!selected) return;
    setOutbound(selected.sip_outbound_trunk_id || '');
    setInbound(selected.sip_inbound_trunk_id || '');
  }, [selected]);

  const save = async () => {
    if (!selectedEmpresaId) return;
    setSaving(true);
    setMsg(null);
    try {
      const res = await apiFetch(`/api/admin/empresas/${selectedEmpresaId}/trunks`, {
        method: 'PUT',
        body: JSON.stringify({
          sip_outbound_trunk_id: outbound,
          sip_inbound_trunk_id: inbound,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const json = await res.json();
      const updated = json?.empresa || {};
      setRows(prev => prev.map(r => (
        r.id === selectedEmpresaId
          ? {
            ...r,
            sip_outbound_trunk_id: updated.sip_outbound_trunk_id ?? null,
            sip_inbound_trunk_id: updated.sip_inbound_trunk_id ?? null,
          }
          : r
      )));
      setMsg({ ok: true, text: 'Troncales guardados correctamente' });
    } catch (err: any) {
      setMsg({ ok: false, text: err?.message || 'No se pudo guardar' });
    } finally {
      setSaving(false);
    }
  };

  if (!isSuperadmin) {
    return (
      <div className="max-w-4xl mx-auto bg-white rounded-2xl border border-amber-200 p-6 text-amber-800">
        Solo superadmin puede editar troncales SIP desde este panel.
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      <header>
        <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
          <Route size={24} className="text-indigo-600" />
          Troncales SIP
        </h1>
        <p className="text-gray-500 text-sm mt-1">
          Configura trunk ID saliente y entrante por empresa.
        </p>
      </header>

      <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6 space-y-5">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2 flex items-center gap-2">
            <Building2 size={15} />
            Empresa
          </label>
          <div className="flex items-center gap-2">
            <select
              value={selectedEmpresaId || ''}
              onChange={(e) => setSelectedEmpresaId(Number(e.target.value))}
              className="flex-1 h-10 px-3 rounded-lg border border-gray-200 bg-white text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 outline-none"
            >
              {rows.map(emp => (
                <option key={emp.id} value={emp.id}>{emp.nombre} (ID {emp.id})</option>
              ))}
            </select>
            <button
              onClick={loadEmpresas}
              className="h-10 px-3 rounded-lg border border-gray-200 hover:bg-gray-50 text-gray-600"
              title="Refrescar"
            >
              <RefreshCw size={15} className={loading ? 'animate-spin' : ''} />
            </button>
          </div>
        </div>

        <div>
          <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">
            Troncal saliente (SIP_OUTBOUND_TRUNK_ID)
          </label>
          <input
            type="text"
            value={outbound}
            onChange={(e) => setOutbound(e.target.value)}
            placeholder="ST_xxxxxxxxxxxx"
            className="w-full h-10 px-4 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400/20 focus:border-indigo-400 transition-all"
          />
          <p className="text-[11px] text-gray-400 mt-1">
            Se usa para llamadas salientes de esta empresa (pruebas, campañas y llamadas manuales).
          </p>
        </div>

        <div>
          <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">
            Troncal entrante
          </label>
          <input
            type="text"
            value={inbound}
            onChange={(e) => setInbound(e.target.value)}
            placeholder="ST_xxxxxxxxxxxx"
            className="w-full h-10 px-4 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400/20 focus:border-indigo-400 transition-all"
          />
          <p className="text-[11px] text-gray-400 mt-1">
            Reservado para uso de llamadas entrantes por empresa.
          </p>
        </div>

        {msg && (
          <div className={`text-sm px-3 py-2 rounded-lg border ${msg.ok ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-red-50 text-red-700 border-red-200'}`}>
            {msg.text}
          </div>
        )}

        <div className="pt-2 flex justify-end">
          <button
            onClick={save}
            disabled={saving || !selectedEmpresaId}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {saving ? <RefreshCw size={14} className="animate-spin" /> : <Save size={14} />}
            Guardar troncales
          </button>
        </div>
      </div>
    </div>
  );
};

export default TrunksView;
