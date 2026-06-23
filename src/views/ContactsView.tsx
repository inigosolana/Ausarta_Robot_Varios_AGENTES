import React, {
  useMemo,
  useRef,
  useState,
} from 'react';
import {
  Users,
  Phone,
  Building2,
  Tag,
  Star,
  Search,
  X,
  ChevronLeft,
  ChevronRight,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Clock,
  Pencil,
  Save,
  Trash2,
  CalendarDays,
  MessageSquareText,
} from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import { useAuth } from '../contexts/AuthContext';
import { apiFetch } from '../lib/apiFetch';
import {
  contactKeys,
  useContactCalls,
  useContactsList,
  useInvalidateContacts,
  type Contact,
} from '../api/contacts';

const DISPOSICION_BADGE: Record<string, string> = {
  completada: 'bg-green-100 text-green-700',
  parcial: 'bg-yellow-100 text-yellow-700',
  rechazada: 'bg-red-100 text-red-700',
  no_contesta: 'bg-gray-100 text-gray-600',
  transferred: 'bg-blue-100 text-blue-700',
};

const SENTIMIENTO_ICON: Record<string, string> = {
  Positivo: '😊',
  Neutral: '😐',
  Negativo: '😟',
};

function scoreColor(s: number) {
  if (s >= 70) return 'text-green-600';
  if (s >= 40) return 'text-yellow-600';
  return 'text-red-500';
}

function formatDuration(seconds: number | null) {
  if (!seconds) return '—';
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

// ─── Component ────────────────────────────────────────────────────────────────

export function ContactsView() {
  const { profile } = useAuth();
  const queryClient = useQueryClient();
  const invalidateContacts = useInvalidateContacts();
  const empresa_id = profile?.empresa_id ?? null;
  const PAGE_SIZE = 25;

  const [page, setPage] = useState(1);
  const [searchQ, setSearchQ] = useState('');
  const [debouncedQ, setDebouncedQ] = useState('');
  const [filterDisposicion, setFilterDisposicion] = useState('');
  const [filterEtiqueta, setFilterEtiqueta] = useState('');
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const listFilters = useMemo(() => ({
    page,
    pageSize: PAGE_SIZE,
    empresaId: empresa_id,
    q: debouncedQ || undefined,
    disposicion: filterDisposicion || undefined,
    etiqueta: filterEtiqueta || undefined,
  }), [page, empresa_id, debouncedQ, filterDisposicion, filterEtiqueta]);

  const { data: contacts = [], isLoading: loading } = useContactsList(listFilters, Boolean(profile));

  const [selected, setSelected] = useState<Contact | null>(null);
  const {
    data: calls = [],
    isLoading: callsLoading,
  } = useContactCalls(selected?.id ?? null, empresa_id, Boolean(selected));
  const [editing, setEditing] = useState(false);
  const [editData, setEditData] = useState<Partial<Contact>>({});
  const [saving, setSaving] = useState(false);
  const [tagInput, setTagInput] = useState('');

  // Feedback
  const [msg, setMsg] = useState<{ type: 'ok' | 'error'; text: string } | null>(null);

  const flash = (type: 'ok' | 'error', text: string) => {
    setMsg({ type, text });
    setTimeout(() => setMsg(null), 4000);
  };

  // ─── Debounce search ────────────────────────────────────────────────────────

  const handleSearchChange = (v: string) => {
    setSearchQ(v);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      setDebouncedQ(v);
      setPage(1);
    }, 300);
  };

  // ─── Save contact ────────────────────────────────────────────────────────────

  const selectContact = (c: Contact) => {
    setSelected(c);
    setEditing(false);
    setEditData({});
  };

  const startEdit = () => {
    if (!selected) return;
    setEditData({
      nombre: selected.nombre ?? '',
      email: selected.email ?? '',
      empresa_nombre: selected.empresa_nombre ?? '',
      notas: selected.notas ?? '',
      etiquetas: [...(selected.etiquetas || [])],
      score: selected.score,
    });
    setEditing(true);
  };

  const saveEdit = async () => {
    if (!selected) return;
    setSaving(true);
    try {
      const params = empresa_id ? `?empresa_id=${empresa_id}` : '';
      const res = await apiFetch(`/api/contacts/${selected.id}${params}`, {
        method: 'PUT',
        body: JSON.stringify(editData),
      });
      if (res.ok) {
        const updated = await res.json();
        setSelected(updated);
        queryClient.setQueryData<Contact[]>(contactKeys.list(listFilters), (prev) =>
          (prev || []).map((c) => (c.id === updated.id ? updated : c)),
        );
        setEditing(false);
        flash('ok', 'Contacto actualizado');
      } else {
        flash('error', 'Error al guardar');
      }
    } catch (e) {
      flash('error', String(e));
    } finally {
      setSaving(false);
    }
  };

  const addTag = () => {
    const t = tagInput.trim();
    if (!t) return;
    const current: string[] = Array.isArray(editData.etiquetas) ? editData.etiquetas as string[] : [];
    if (!current.includes(t)) {
      setEditData(prev => ({ ...prev, etiquetas: [...current, t] }));
    }
    setTagInput('');
  };

  const removeTag = (tag: string) => {
    setEditData(prev => ({
      ...prev,
      etiquetas: (prev.etiquetas as string[] || []).filter(t => t !== tag),
    }));
  };

  // ─── Delete contact ──────────────────────────────────────────────────────────

  const deleteContact = async () => {
    if (!selected) return;
    if (!confirm(`¿Eliminar el contacto "${selected.nombre || selected.telefono}"?`)) return;
    try {
      const params = empresa_id ? `?empresa_id=${empresa_id}` : '';
      await apiFetch(`/api/contacts/${selected.id}${params}`, { method: 'DELETE' });
      setSelected(null);
      queryClient.setQueryData<Contact[]>(contactKeys.list(listFilters), (prev) =>
        (prev || []).filter((c) => c.id !== selected.id),
      );
      invalidateContacts();
      flash('ok', 'Contacto eliminado');
    } catch (e) {
      flash('error', String(e));
    }
  };

  // ─── Render ──────────────────────────────────────────────────────────────────

  return (
    <div className="flex h-full overflow-hidden">
      {/* Left: list */}
      <div className={`flex flex-col ${selected ? 'w-1/2' : 'w-full'} transition-all duration-300`}>
        <div className="p-5 flex flex-col gap-4 bg-white border-b border-gray-100">
          {/* Header */}
          <div className="flex items-center gap-3">
            <div className="p-2 bg-blue-50 rounded-lg">
              <Users size={22} className="text-blue-600" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-gray-900">Contactos</h1>
              <p className="text-xs text-gray-500">Ficha unificada con historial de llamadas</p>
            </div>
          </div>

          {/* Flash */}
          {msg && (
            <div className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm ${
              msg.type === 'ok'
                ? 'bg-green-50 text-green-700 border border-green-200'
                : 'bg-red-50 text-red-700 border border-red-200'
            }`}>
              {msg.type === 'ok' ? <CheckCircle2 size={15} /> : <AlertCircle size={15} />}
              <span>{msg.text}</span>
              <button onClick={() => setMsg(null)} className="ml-auto"><X size={13} /></button>
            </div>
          )}

          {/* Filters */}
          <div className="flex gap-2 flex-wrap">
            <div className="relative flex-1 min-w-[180px]">
              <Search size={15} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                type="text"
                value={searchQ}
                onChange={e => handleSearchChange(e.target.value)}
                placeholder="Nombre o teléfono…"
                className="w-full pl-8 pr-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
              />
            </div>
            <select
              value={filterDisposicion}
              onChange={e => { setFilterDisposicion(e.target.value); setPage(1); }}
              className="border border-gray-200 rounded-lg px-2 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
            >
              <option value="">Disposición</option>
              <option value="completada">Completada</option>
              <option value="parcial">Parcial</option>
              <option value="rechazada">Rechazada</option>
              <option value="no_contesta">No contesta</option>
            </select>
          </div>
        </div>

        {/* Table */}
        <div className="flex-1 overflow-auto">
          {loading ? (
            <div className="flex items-center justify-center py-16 text-gray-400">
              <Loader2 size={24} className="animate-spin mr-2" /> Cargando…
            </div>
          ) : contacts.length === 0 ? (
            <div className="text-center py-16 text-gray-400 text-sm">
              No hay contactos con esos filtros
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-gray-50 sticky top-0 z-10">
                <tr className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">
                  <th className="px-4 py-3">Contacto</th>
                  <th className="px-4 py-3 hidden md:table-cell">Empresa</th>
                  <th className="px-4 py-3 hidden sm:table-cell">Llamadas</th>
                  <th className="px-4 py-3 hidden lg:table-cell">Disposición</th>
                  <th className="px-4 py-3">Score</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {contacts.map(c => (
                  <tr
                    key={c.id}
                    onClick={() => selectContact(c)}
                    className={`cursor-pointer hover:bg-blue-50 transition-colors ${
                      selected?.id === c.id ? 'bg-blue-50' : ''
                    }`}
                  >
                    <td className="px-4 py-3">
                      <div className="font-medium text-gray-800">
                        {c.nombre || <span className="text-gray-400 italic">Sin nombre</span>}
                      </div>
                      <div className="text-xs text-gray-400 flex items-center gap-1 mt-0.5">
                        <Phone size={11} /> {c.telefono}
                      </div>
                    </td>
                    <td className="px-4 py-3 hidden md:table-cell text-gray-600">
                      {c.empresa_nombre || '—'}
                    </td>
                    <td className="px-4 py-3 hidden sm:table-cell text-gray-600">
                      {c.total_llamadas}
                    </td>
                    <td className="px-4 py-3 hidden lg:table-cell">
                      {c.ultima_disposicion ? (
                        <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                          DISPOSICION_BADGE[c.ultima_disposicion] ?? 'bg-gray-100 text-gray-600'
                        }`}>
                          {c.ultima_disposicion}
                        </span>
                      ) : '—'}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`font-bold ${scoreColor(c.score)}`}>{c.score}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Pagination */}
        <div className="p-3 border-t border-gray-100 flex items-center justify-between text-sm text-gray-500">
          <span>Página {page}</span>
          <div className="flex gap-2">
            <button
              disabled={page <= 1}
              onClick={() => setPage(p => p - 1)}
              className="p-1.5 rounded hover:bg-gray-100 disabled:opacity-40"
            >
              <ChevronLeft size={16} />
            </button>
            <button
              disabled={contacts.length < PAGE_SIZE}
              onClick={() => setPage(p => p + 1)}
              className="p-1.5 rounded hover:bg-gray-100 disabled:opacity-40"
            >
              <ChevronRight size={16} />
            </button>
          </div>
        </div>
      </div>

      {/* Right: detail panel */}
      {selected && (
        <div className="w-1/2 flex flex-col border-l border-gray-100 bg-white overflow-auto">
          {/* Panel header */}
          <div className="p-4 border-b border-gray-100 flex items-center justify-between">
            <div className="font-semibold text-gray-800 truncate">
              {selected.nombre || selected.telefono}
            </div>
            <div className="flex items-center gap-2">
              {!editing ? (
                <button
                  onClick={startEdit}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-blue-600 bg-blue-50 rounded-lg hover:bg-blue-100"
                >
                  <Pencil size={13} /> Editar
                </button>
              ) : (
                <button
                  onClick={saveEdit}
                  disabled={saving}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-40"
                >
                  {saving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
                  Guardar
                </button>
              )}
              <button
                onClick={deleteContact}
                className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg"
              >
                <Trash2 size={15} />
              </button>
              <button onClick={() => setSelected(null)} className="p-1.5 hover:bg-gray-100 rounded-lg">
                <X size={16} />
              </button>
            </div>
          </div>

          <div className="flex-1 overflow-auto p-5 space-y-6">
            {/* Score gauge */}
            <div className="flex items-center gap-4 bg-gray-50 rounded-xl p-4">
              <div className="text-center">
                <div className={`text-3xl font-bold ${scoreColor(editing ? (editData.score ?? selected.score) : selected.score)}`}>
                  {editing ? (editData.score ?? selected.score) : selected.score}
                </div>
                <div className="text-xs text-gray-500 mt-0.5">Score</div>
              </div>
              <div className="flex-1">
                {editing && (
                  <input
                    type="range"
                    min={0} max={100}
                    value={editData.score ?? selected.score}
                    onChange={e => setEditData(prev => ({ ...prev, score: parseInt(e.target.value) }))}
                    className="w-full accent-blue-500"
                  />
                )}
                <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-gray-600 mt-1">
                  <div className="flex items-center gap-1.5">
                    <Phone size={12} className="text-gray-400" />
                    <span>{selected.total_llamadas} llamadas</span>
                  </div>
                  {selected.ultima_llamada && (
                    <div className="flex items-center gap-1.5">
                      <Clock size={12} className="text-gray-400" />
                      <span>{new Date(selected.ultima_llamada).toLocaleDateString('es-ES')}</span>
                    </div>
                  )}
                  {selected.ultima_disposicion && (
                    <div className="col-span-2">
                      <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                        DISPOSICION_BADGE[selected.ultima_disposicion] ?? 'bg-gray-100 text-gray-600'
                      }`}>
                        {selected.ultima_disposicion}
                      </span>
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* Editable fields */}
            <div className="space-y-3">
              {editing ? (
                <>
                  <FieldInput label="Nombre" value={editData.nombre ?? ''} onChange={v => setEditData(p => ({ ...p, nombre: v }))} />
                  <FieldInput label="Email" value={editData.email ?? ''} onChange={v => setEditData(p => ({ ...p, email: v }))} type="email" />
                  <FieldInput label="Empresa" value={editData.empresa_nombre ?? ''} onChange={v => setEditData(p => ({ ...p, empresa_nombre: v }))} icon={<Building2 size={13} />} />
                  <div>
                    <label className="text-xs font-medium text-gray-500 mb-1 block">Notas</label>
                    <textarea
                      rows={3}
                      value={editData.notas ?? ''}
                      onChange={e => setEditData(p => ({ ...p, notas: e.target.value }))}
                      className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 resize-none"
                    />
                  </div>
                  {/* Tags */}
                  <div>
                    <label className="text-xs font-medium text-gray-500 mb-1 block flex items-center gap-1">
                      <Tag size={12} /> Etiquetas
                    </label>
                    <div className="flex flex-wrap gap-1.5 mb-2">
                      {(editData.etiquetas as string[] || []).map(t => (
                        <span key={t} className="flex items-center gap-1 px-2 py-0.5 bg-indigo-100 text-indigo-700 rounded-full text-xs">
                          {t}
                          <button onClick={() => removeTag(t)}><X size={11} /></button>
                        </span>
                      ))}
                    </div>
                    <div className="flex gap-2">
                      <input
                        type="text"
                        value={tagInput}
                        onChange={e => setTagInput(e.target.value)}
                        onKeyDown={e => e.key === 'Enter' && addTag()}
                        placeholder="Nueva etiqueta…"
                        className="flex-1 border border-gray-200 rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-400"
                      />
                      <button
                        onClick={addTag}
                        className="px-3 py-1.5 bg-indigo-600 text-white text-xs rounded-lg hover:bg-indigo-700"
                      >
                        +
                      </button>
                    </div>
                  </div>
                </>
              ) : (
                <>
                  <InfoRow label="Teléfono" value={selected.telefono} icon={<Phone size={13} />} />
                  {selected.email && <InfoRow label="Email" value={selected.email} />}
                  {selected.empresa_nombre && <InfoRow label="Empresa" value={selected.empresa_nombre} icon={<Building2 size={13} />} />}
                  {selected.notas && (
                    <div>
                      <p className="text-xs font-medium text-gray-500 mb-1">Notas</p>
                      <p className="text-sm text-gray-700 bg-gray-50 rounded-lg p-3">{selected.notas}</p>
                    </div>
                  )}
                  {selected.etiquetas?.length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                      {selected.etiquetas.map(t => (
                        <span key={t} className="px-2 py-0.5 bg-indigo-100 text-indigo-700 rounded-full text-xs flex items-center gap-1">
                          <Tag size={11} /> {t}
                        </span>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>

            {/* Call history */}
            <div>
              <h3 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
                <CalendarDays size={15} className="text-blue-500" /> Historial de llamadas
              </h3>
              {callsLoading ? (
                <div className="flex items-center text-gray-400 text-sm gap-2">
                  <Loader2 size={16} className="animate-spin" /> Cargando…
                </div>
              ) : calls.length === 0 ? (
                <p className="text-sm text-gray-400">No hay llamadas registradas</p>
              ) : (
                <div className="space-y-3">
                  {calls.map(call => (
                    <div key={call.id} className="border border-gray-100 rounded-xl p-3 bg-gray-50">
                      <div className="flex items-center justify-between mb-1">
                        <div className="flex items-center gap-2">
                          {call.disposicion && (
                            <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                              DISPOSICION_BADGE[call.disposicion] ?? 'bg-gray-100 text-gray-600'
                            }`}>
                              {call.disposicion}
                            </span>
                          )}
                          {call.sentimiento && (
                            <span title={call.sentimiento} className="text-base">
                              {SENTIMIENTO_ICON[call.sentimiento] ?? ''}
                            </span>
                          )}
                        </div>
                        <div className="text-xs text-gray-400 flex items-center gap-1">
                          <Clock size={11} />
                          {call.duracion_segundos != null ? formatDuration(call.duracion_segundos) : '—'}
                          {call.fecha && (
                            <span className="ml-2">
                              {new Date(call.fecha).toLocaleDateString('es-ES')}
                            </span>
                          )}
                        </div>
                      </div>
                      {call.resumen && (
                        <p className="text-xs text-gray-600 leading-relaxed flex gap-1.5 mt-1">
                          <MessageSquareText size={12} className="text-gray-400 shrink-0 mt-0.5" />
                          {call.resumen}
                        </p>
                      )}
                      {call.comentarios && !call.resumen && (
                        <p className="text-xs text-gray-500 italic mt-1">{call.comentarios}</p>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Helper UI components ─────────────────────────────────────────────────────

function InfoRow({
  label,
  value,
  icon,
}: {
  label: string;
  value: string;
  icon?: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-2 text-sm">
      {icon && <span className="text-gray-400">{icon}</span>}
      <span className="text-gray-500 w-20 shrink-0 text-xs">{label}</span>
      <span className="text-gray-800 font-medium">{value}</span>
    </div>
  );
}

function FieldInput({
  label,
  value,
  onChange,
  type = 'text',
  icon,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  icon?: React.ReactNode;
}) {
  return (
    <div>
      <label className="text-xs font-medium text-gray-500 mb-1 block flex items-center gap-1">
        {icon} {label}
      </label>
      <input
        type={type}
        value={value}
        onChange={e => onChange(e.target.value)}
        className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
      />
    </div>
  );
}

export default ContactsView;
