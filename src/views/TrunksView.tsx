import React, { useEffect, useMemo, useState, useCallback } from 'react';
import { Building2, Route, Save, RefreshCw, Plus, Pencil, Trash2, X, Phone, Server, AlertTriangle } from 'lucide-react';
import { apiFetch, fetchTrunks, type TelephonyTrunk } from '../lib/apiFetch';
import { useAuth } from '../contexts/AuthContext';

type EmpresaRow = {
  id: number;
  nombre: string;
  sip_outbound_trunk_id?: string | null;
  sip_inbound_trunk_id?: string | null;
};

type Extension = {
  id: string;
  extension_number: string;
  extension_name: string | null;
  departamento: string | null;
};

type ExtModalState = {
  open: boolean;
  mode: 'add' | 'edit';
  ext: Partial<Extension>;
};

const TrunksView: React.FC = () => {
  const { profile, isPlatformOwner } = useAuth();
  const [rows, setRows] = useState<EmpresaRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedEmpresaId, setSelectedEmpresaId] = useState<number | null>(null);
  const [outbound, setOutbound] = useState('');
  const [inbound, setInbound] = useState('');
  const [saving, setSaving] = useState(false);
  const [citeliaDdi, setCiteliaDdi] = useState('');
  const [creatingCitelia, setCreatingCitelia] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [livekitTrunks, setLivekitTrunks] = useState<TelephonyTrunk[]>([]);
  const [yeastarTrunks, setYeastarTrunks] = useState<TelephonyTrunk[]>([]);
  const [trunksLoading, setTrunksLoading] = useState(false);
  const [trunksMsg, setTrunksMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [trunkErrors, setTrunkErrors] = useState<Record<string, string>>({});

  // Extensions state
  const [extensions, setExtensions] = useState<Extension[]>([]);
  const [extLoading, setExtLoading] = useState(false);
  const [extMsg, setExtMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [extStatuses, setExtStatuses] = useState<Record<string, string>>({});
  const [syncingExt, setSyncingExt] = useState(false);
  const [statusLoading, setStatusLoading] = useState(false);
  const [extModal, setExtModal] = useState<ExtModalState>({
    open: false,
    mode: 'add',
    ext: {},
  });
  const [extSaving, setExtSaving] = useState(false);
  const [deletingExtId, setDeletingExtId] = useState<string | null>(null);

  const canManageTrunks = isPlatformOwner || profile?.role === 'superadmin';

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

  const loadExtensions = useCallback(async (empresaId: number) => {
    setExtLoading(true);
    setExtMsg(null);
    try {
      const res = await apiFetch(`/api/empresas/${empresaId}/extensions`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: Extension[] = await res.json();
      setExtensions(data || []);
    } catch (err: any) {
      setExtMsg({ ok: false, text: err?.message || 'No se pudieron cargar las extensiones' });
    } finally {
      setExtLoading(false);
    }
  }, []);

  const loadAvailableTrunks = useCallback(async (empresaId: number) => {
    setTrunksLoading(true);
    setTrunksMsg(null);
    try {
      const data = await fetchTrunks(empresaId);
      setLivekitTrunks(data.livekit_trunks || []);
      setYeastarTrunks(data.yeastar_trunks || []);
      setTrunkErrors(data.errors || {});
    } catch (err: any) {
      setLivekitTrunks([]);
      setYeastarTrunks([]);
      setTrunkErrors({});
      setTrunksMsg({ ok: false, text: err?.message || 'No se pudieron cargar las troncales disponibles' });
    } finally {
      setTrunksLoading(false);
    }
  }, []);

  const syncExtensionsFromYeastar = async () => {
    if (!selectedEmpresaId) return;
    setSyncingExt(true);
    setExtMsg(null);
    try {
      const res = await apiFetch(`/api/empresas/${selectedEmpresaId}/extensions/sync`, {
        method: 'POST',
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setExtensions(data.extensions || []);
      setExtMsg({ ok: true, text: `${data.synced || 0} extensiones sincronizadas desde Yeastar` });
    } catch (err: any) {
      setExtMsg({ ok: false, text: err?.message || 'No se pudo sincronizar con Yeastar' });
    } finally {
      setSyncingExt(false);
    }
  };

  const refreshExtensionStatuses = async () => {
    if (!selectedEmpresaId) return;
    setStatusLoading(true);
    setExtMsg(null);
    try {
      const res = await apiFetch(`/api/empresas/${selectedEmpresaId}/extensions/statuses`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setExtStatuses(data.statuses || {});
    } catch (err: any) {
      setExtMsg({ ok: false, text: err?.message || 'No se pudieron consultar estados Yeastar' });
    } finally {
      setStatusLoading(false);
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
    loadExtensions(selected.id);
    loadAvailableTrunks(selected.id);
  }, [selected, loadExtensions, loadAvailableTrunks]);

  const phoneText = (trunk: TelephonyTrunk) => {
    const numbers = trunk.phone_numbers || [];
    return numbers.length ? numbers.join(', ') : 'Sin números';
  };

  const renderTrunksTable = (
    title: string,
    trunks: TelephonyTrunk[],
    accentClass: string,
    emptyText: string,
  ) => (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
      <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Server size={16} className={accentClass} />
          <h2 className="text-sm font-bold text-gray-800">{title}</h2>
          <span className="px-2 py-0.5 bg-gray-100 rounded-full text-[11px] text-gray-500 font-medium">
            {trunks.length}
          </span>
        </div>
      </div>

      {trunksLoading ? (
        <div className="flex items-center gap-2 text-gray-400 text-sm p-5">
          <RefreshCw size={14} className="animate-spin" /> Cargando troncales...
        </div>
      ) : trunks.length === 0 ? (
        <div className="text-sm text-gray-400 p-5">{emptyText}</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-xs uppercase text-gray-500">
              <tr>
                <th className="text-left font-semibold px-4 py-3">ID</th>
                <th className="text-left font-semibold px-4 py-3">Nombre</th>
                <th className="text-left font-semibold px-4 py-3">Números</th>
                <th className="text-left font-semibold px-4 py-3">Estado</th>
                <th className="text-left font-semibold px-4 py-3">Proveedor</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {trunks.map((trunk, index) => (
                <tr key={`${trunk.provider}-${trunk.id}-${index}`} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-mono text-xs text-gray-700">{trunk.id || '-'}</td>
                  <td className="px-4 py-3 text-gray-700">
                    {trunk.name || '-'}
                    {trunk.direction && (
                      <span className="ml-2 rounded-full bg-gray-100 px-2 py-0.5 text-[10px] uppercase text-gray-500">
                        {trunk.direction}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-gray-600">{phoneText(trunk)}</td>
                  <td className="px-4 py-3">
                    <span className="rounded-full bg-emerald-50 px-2 py-1 text-xs font-medium text-emerald-700">
                      {trunk.status || 'available'}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-500">{trunk.provider}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );

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

  const createCiteliaTrunk = async () => {
    if (!selectedEmpresaId || !citeliaDdi.trim()) return;
    setCreatingCitelia(true);
    setMsg(null);
    try {
      const res = await apiFetch(`/api/empresas/${selectedEmpresaId}/outbound-trunks/citelia`, {
        method: 'POST',
        body: JSON.stringify({ ddi: citeliaDdi.trim() }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const json = await res.json();
      const trunk = json?.trunk || {};
      const updated = json?.empresa || {};
      if (trunk?.id) {
        setOutbound(trunk.id);
        setRows(prev => prev.map(r => (
          r.id === selectedEmpresaId
            ? {
              ...r,
              sip_outbound_trunk_id: updated.sip_outbound_trunk_id ?? trunk.id,
              sip_inbound_trunk_id: updated.sip_inbound_trunk_id ?? r.sip_inbound_trunk_id ?? null,
            }
            : r
        )));
      }
      setMsg({
        ok: true,
        text: trunk?.created
          ? `Troncal CITELIA creada correctamente (${trunk.id})`
          : `Troncal CITELIA reutilizada (${trunk.id})`,
      });
      await loadAvailableTrunks(selectedEmpresaId);
    } catch (err: any) {
      setMsg({ ok: false, text: err?.message || 'No se pudo crear la troncal CITELIA' });
    } finally {
      setCreatingCitelia(false);
    }
  };

  const openAddExt = () => {
    setExtModal({ open: true, mode: 'add', ext: {} });
  };

  const openEditExt = (ext: Extension) => {
    setExtModal({ open: true, mode: 'edit', ext: { ...ext } });
  };

  const closeModal = () => {
    setExtModal({ open: false, mode: 'add', ext: {} });
  };

  const saveExtension = async () => {
    if (!selectedEmpresaId) return;
    const { ext, mode } = extModal;
    if (!ext.extension_number?.trim()) return;

    setExtSaving(true);
    setExtMsg(null);
    try {
      const body = JSON.stringify({
        extension_number: ext.extension_number.trim(),
        extension_name: ext.extension_name?.trim() || '',
        departamento: ext.departamento?.trim() || '',
      });

      let res: Response;
      if (mode === 'add') {
        res = await apiFetch(`/api/empresas/${selectedEmpresaId}/extensions`, {
          method: 'POST',
          body,
        });
      } else {
        res = await apiFetch(`/api/empresas/${selectedEmpresaId}/extensions/${ext.id}`, {
          method: 'PUT',
          body,
        });
      }

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }

      await loadExtensions(selectedEmpresaId);
      closeModal();
      setExtMsg({ ok: true, text: mode === 'add' ? 'Extensión creada' : 'Extensión actualizada' });
    } catch (err: any) {
      setExtMsg({ ok: false, text: err?.message || 'No se pudo guardar la extensión' });
    } finally {
      setExtSaving(false);
    }
  };

  const deleteExtension = async (extId: string) => {
    if (!selectedEmpresaId) return;
    setDeletingExtId(extId);
    setExtMsg(null);
    try {
      const res = await apiFetch(`/api/empresas/${selectedEmpresaId}/extensions/${extId}`, {
        method: 'DELETE',
      });
      if (!res.ok && res.status !== 204) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      setExtensions(prev => prev.filter(e => e.id !== extId));
      setExtMsg({ ok: true, text: 'Extensión eliminada' });
    } catch (err: any) {
      setExtMsg({ ok: false, text: err?.message || 'No se pudo eliminar' });
    } finally {
      setDeletingExtId(null);
    }
  };

  if (!canManageTrunks) {
    return (
      <div className="max-w-4xl mx-auto bg-white rounded-2xl border border-amber-200 p-6 text-amber-800">
        Solo superadmin o admin de Ausarta puede editar troncales SIP desde este panel.
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      <header>
        <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
          <Route size={24} className="text-indigo-600" />
          Troncales SIP y Extensiones
        </h1>
        <p className="text-gray-500 text-sm mt-1">
          Configura trunk ID saliente/entrante y extensiones Yeastar por empresa.
        </p>
      </header>

      {/* ── Selector de empresa ─────────────────────────────────────────── */}
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

        {/* ── Troncales SIP ─────────────────────────────────────────────── */}
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

        <div className="rounded-xl border border-blue-100 bg-blue-50 p-4 space-y-3">
          <div>
            <h3 className="text-sm font-bold text-blue-900">Crear troncal saliente CITELIA_SBC</h3>
            <p className="text-xs text-blue-700 mt-1">
              Host, puerto, dominio y transporte son fijos. Solo necesitas indicar el DDI de esta empresa.
            </p>
          </div>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <div className="flex-1">
              <label className="block text-xs font-semibold text-blue-800 uppercase tracking-wider mb-1.5">
                DDI
              </label>
              <input
                type="text"
                value={citeliaDdi}
                onChange={(e) => setCiteliaDdi(e.target.value)}
                placeholder="842840650"
                className="w-full h-10 px-4 border border-blue-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-400/20 focus:border-blue-400 transition-all"
              />
            </div>
            <button
              onClick={createCiteliaTrunk}
              disabled={creatingCitelia || !selectedEmpresaId || !citeliaDdi.trim()}
              className="inline-flex items-center justify-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {creatingCitelia ? <RefreshCw size={14} className="animate-spin" /> : <Plus size={14} />}
              Crear CITELIA
            </button>
          </div>
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

      {selectedEmpresaId && (
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-base font-bold text-gray-900">Troncales disponibles</h2>
              <p className="text-xs text-gray-500">Consulta directa de LiveKit y Yeastar para la empresa seleccionada.</p>
            </div>
            <button
              onClick={() => loadAvailableTrunks(selectedEmpresaId)}
              disabled={trunksLoading}
              className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-gray-200 bg-white text-xs font-semibold text-gray-600 hover:bg-gray-50 disabled:opacity-50"
              title="Refrescar troncales disponibles"
            >
              <RefreshCw size={13} className={trunksLoading ? 'animate-spin' : ''} />
              Refrescar
            </button>
          </div>

          {trunksMsg && (
            <div className={`text-sm px-3 py-2 rounded-lg border ${trunksMsg.ok ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-red-50 text-red-700 border-red-200'}`}>
              {trunksMsg.text}
            </div>
          )}

          {Object.keys(trunkErrors).length > 0 && (
            <div className="flex gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
              <AlertTriangle size={14} className="mt-0.5 shrink-0" />
              <span>
                Algunas fuentes no respondieron: {Object.entries(trunkErrors).map(([key, value]) => `${key}: ${value}`).join(' | ')}
              </span>
            </div>
          )}

          {renderTrunksTable(
            'Troncales LiveKit Disponibles',
            livekitTrunks,
            'text-indigo-600',
            'No hay troncales LiveKit disponibles o no se pudieron consultar.',
          )}
          {renderTrunksTable(
            'Troncales Yeastar',
            yeastarTrunks,
            'text-emerald-600',
            'No hay troncales Yeastar configuradas para esta empresa.',
          )}
        </section>
      )}

      {/* ── Extensiones Yeastar ─────────────────────────────────────────── */}
      {selectedEmpresaId && (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6 space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Phone size={17} className="text-emerald-600" />
              <h2 className="text-base font-bold text-gray-800">Extensiones Yeastar</h2>
              <span className="px-2 py-0.5 bg-gray-100 rounded-full text-[11px] text-gray-500 font-medium">
                {extensions.length}
              </span>
            </div>
            <div className="flex flex-wrap items-center justify-end gap-2">
              <button
                onClick={refreshExtensionStatuses}
                disabled={statusLoading || extensions.length === 0}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-gray-200 bg-white text-gray-600 text-xs font-semibold hover:bg-gray-50 transition-colors disabled:opacity-50"
              >
                <RefreshCw size={13} className={statusLoading ? 'animate-spin' : ''} />
                Estados
              </button>
              <button
                onClick={syncExtensionsFromYeastar}
                disabled={syncingExt}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-emerald-200 bg-emerald-50 text-emerald-700 text-xs font-semibold hover:bg-emerald-100 transition-colors disabled:opacity-50"
              >
                <RefreshCw size={13} className={syncingExt ? 'animate-spin' : ''} />
                Sincronizar PBX
              </button>
              <button
                onClick={openAddExt}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-600 text-white text-xs font-semibold hover:bg-emerald-700 transition-colors"
            >
              <Plus size={13} />
              Añadir extensión
              </button>
            </div>
          </div>

          {extMsg && (
            <div className={`text-xs px-3 py-2 rounded-lg border ${extMsg.ok ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-red-50 text-red-700 border-red-200'}`}>
              {extMsg.text}
            </div>
          )}

          {extLoading ? (
            <div className="flex items-center gap-2 text-gray-400 text-sm py-4">
              <RefreshCw size={14} className="animate-spin" /> Cargando extensiones…
            </div>
          ) : extensions.length === 0 ? (
            <div className="text-center py-8 text-gray-400">
              <Phone size={28} className="mx-auto mb-2 text-gray-200" />
              <p className="text-sm">Sin extensiones configuradas</p>
              <p className="text-xs mt-1 text-gray-300">Añade extensiones Yeastar para transferencias dinámicas</p>
            </div>
          ) : (
            <div className="space-y-2">
              {extensions.map(ext => (
                <div
                  key={ext.id}
                  className="flex items-center justify-between p-3 border border-gray-100 rounded-xl hover:border-gray-200 transition-colors"
                >
                  <div className="flex items-center gap-3">
                    <div className="w-9 h-9 rounded-xl bg-emerald-50 flex items-center justify-center">
                      <Phone size={15} className="text-emerald-600" />
                    </div>
                    <div>
                      <p className="text-sm font-bold text-gray-800">
                        ext {ext.extension_number}
                        {ext.extension_name && (
                          <span className="font-normal text-gray-600"> — {ext.extension_name}</span>
                        )}
                      </p>
                      {ext.departamento && (
                        <p className="text-[11px] text-gray-400">{ext.departamento}</p>
                      )}
                      {extStatuses[ext.extension_number] && (
                        <span className={`mt-1 inline-flex rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                          extStatuses[ext.extension_number] === 'Idle'
                            ? 'bg-emerald-50 text-emerald-700'
                            : extStatuses[ext.extension_number] === 'Busy'
                              ? 'bg-amber-50 text-amber-700'
                              : 'bg-gray-100 text-gray-600'
                        }`}>
                          {extStatuses[ext.extension_number]}
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <button
                      onClick={() => openEditExt(ext)}
                      className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400 hover:text-gray-600 transition-colors"
                      title="Editar"
                    >
                      <Pencil size={13} />
                    </button>
                    <button
                      onClick={() => deleteExtension(ext.id)}
                      disabled={deletingExtId === ext.id}
                      className="p-1.5 rounded-lg hover:bg-red-50 text-gray-400 hover:text-red-500 transition-colors disabled:opacity-50"
                      title="Eliminar"
                    >
                      {deletingExtId === ext.id
                        ? <RefreshCw size={13} className="animate-spin" />
                        : <Trash2 size={13} />
                      }
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Modal de extensión ──────────────────────────────────────────── */}
      {extModal.open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm">
          <div className="bg-white rounded-2xl shadow-2xl p-6 w-full max-w-sm space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="font-bold text-gray-800">
                {extModal.mode === 'add' ? 'Nueva extensión' : 'Editar extensión'}
              </h3>
              <button onClick={closeModal} className="p-1 rounded-lg hover:bg-gray-100 text-gray-400">
                <X size={16} />
              </button>
            </div>

            <div className="space-y-3">
              <div>
                <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1">
                  Número de extensión *
                </label>
                <input
                  type="text"
                  value={extModal.ext.extension_number || ''}
                  onChange={(e) => setExtModal(m => ({ ...m, ext: { ...m.ext, extension_number: e.target.value } }))}
                  placeholder="1001"
                  className="w-full h-10 px-3 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-emerald-400/20 focus:border-emerald-400"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1">
                  Nombre
                </label>
                <input
                  type="text"
                  value={extModal.ext.extension_name || ''}
                  onChange={(e) => setExtModal(m => ({ ...m, ext: { ...m.ext, extension_name: e.target.value } }))}
                  placeholder="Ana García"
                  className="w-full h-10 px-3 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-emerald-400/20 focus:border-emerald-400"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1">
                  Departamento
                </label>
                <input
                  type="text"
                  value={extModal.ext.departamento || ''}
                  onChange={(e) => setExtModal(m => ({ ...m, ext: { ...m.ext, departamento: e.target.value } }))}
                  placeholder="Ventas"
                  className="w-full h-10 px-3 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-emerald-400/20 focus:border-emerald-400"
                />
              </div>
            </div>

            <div className="flex gap-2 pt-2">
              <button
                onClick={closeModal}
                className="flex-1 h-10 rounded-xl border border-gray-200 text-sm text-gray-600 hover:bg-gray-50"
              >
                Cancelar
              </button>
              <button
                onClick={saveExtension}
                disabled={extSaving || !extModal.ext.extension_number?.trim()}
                className="flex-1 h-10 rounded-xl bg-emerald-600 text-white text-sm font-semibold hover:bg-emerald-700 disabled:opacity-50 flex items-center justify-center gap-2"
              >
                {extSaving ? <RefreshCw size={14} className="animate-spin" /> : <Save size={14} />}
                Guardar
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default TrunksView;
