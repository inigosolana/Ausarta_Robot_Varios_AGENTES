import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  CheckCircle2,
  AlertCircle,
  Loader2,
  X,
  Building2,
  Users,
} from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { supabase } from '../lib/supabase';
import type { Empresa } from '../types';
import { KNOWLEDGE_FILE_ACCEPT } from '../lib/knowledgeUpload';
import './knowledge-base.css';

interface KBDoc {
  titulo: string;
  source_type: string;
  chunks: number;
  created_at: string;
  ids: number[];
}

interface SearchResult {
  titulo: string;
  contenido: string;
  similarity: number;
}

const SOURCE_LABELS: Record<string, string> = {
  manual: 'Manual',
  pdf: 'PDF',
  web: 'Web',
  faq: 'FAQ',
  policy: 'Política',
};

const SOURCE_BADGE: Record<string, string> = {
  pdf: 'bg-violet-100 text-violet-700 border-violet-200 dark:bg-violet-500/10 dark:text-violet-300 dark:border-violet-500/25',
  web: 'bg-emerald-100 text-emerald-700 border-emerald-200 dark:bg-primary/10 dark:text-primary dark:border-primary/25',
  manual: 'bg-cyan-100 text-cyan-700 border-cyan-200 dark:bg-cyan-500/10 dark:text-cyan-300 dark:border-cyan-500/25',
  faq: 'bg-amber-100 text-amber-700 border-amber-200 dark:bg-amber-500/10 dark:text-amber-300 dark:border-amber-500/25',
  policy: 'bg-rose-100 text-rose-700 border-rose-200 dark:bg-rose-500/10 dark:text-rose-300 dark:border-rose-500/25',
  md: 'bg-cyan-100 text-cyan-700 border-cyan-200 dark:bg-cyan-500/10 dark:text-cyan-300 dark:border-cyan-500/25',
  json: 'bg-yellow-100 text-yellow-800 border-yellow-200 dark:bg-yellow-500/10 dark:text-yellow-300 dark:border-yellow-500/25',
};

const API_BASE =
  (import.meta as { env?: { VITE_API_URL?: string } }).env?.VITE_API_URL ?? '';

function MaterialIcon({ name, className = '' }: { name: string; className?: string }) {
  return <span className={`material-symbols-outlined kb-icon ${className}`}>{name}</span>;
}

function sourceBadgeClass(type: string): string {
  const key = type.toLowerCase();
  return SOURCE_BADGE[key] ?? 'bg-gray-100 text-gray-600 border-gray-200 dark:bg-gray-800 dark:text-gray-400 dark:border-gray-700';
}

function matchColor(similarity: number): string {
  if (similarity >= 0.9) return 'text-emerald-700 border-emerald-200 bg-emerald-50 dark:text-primary dark:border-primary/25 dark:bg-primary/10';
  if (similarity >= 0.75) return 'text-cyan-700 border-cyan-200 bg-cyan-50 dark:text-cyan-300 dark:border-cyan-500/25 dark:bg-cyan-500/10';
  return 'text-gray-600 border-gray-200 bg-gray-50 dark:text-gray-400 dark:border-gray-700 dark:bg-gray-800';
}

export function KnowledgeBaseView() {
  const { session, profile, isPlatformOwner } = useAuth();
  const token = session?.access_token ?? '';
  const [empresas, setEmpresas] = useState<Empresa[]>([]);
  const [selectedEmpresaId, setSelectedEmpresaId] = useState<number | null>(profile?.empresa_id ?? null);
  const empresa_id = isPlatformOwner ? selectedEmpresaId : profile?.empresa_id ?? null;

  const [docs, setDocs] = useState<KBDoc[]>([]);
  const [loading, setLoading] = useState(true);
  const [msg, setMsg] = useState<{ type: 'ok' | 'error'; text: string } | null>(null);

  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadTitle, setUploadTitle] = useState('');
  const [uploadType, setUploadType] = useState('manual');
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [urlInput, setUrlInput] = useState('');
  const [urlTitle, setUrlTitle] = useState('');
  const [uploadingUrl, setUploadingUrl] = useState(false);

  const [searchQ, setSearchQ] = useState('');
  const [searching, setSearching] = useState(false);
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searchThreshold, setSearchThreshold] = useState(0.7);

  const [deletingTitle, setDeletingTitle] = useState<string | null>(null);
  const [companyContext, setCompanyContext] = useState('');
  const [savingContext, setSavingContext] = useState(false);
  const [generatingContext, setGeneratingContext] = useState(false);

  const headers = { Authorization: `Bearer ${token}` };

  const selectedEmpresaName = useMemo(() => {
    if (!empresa_id) return null;
    return empresas.find(e => Number(e.id) === empresa_id)?.nombre
      ?? (profile?.empresa_id === empresa_id ? profile?.empresas?.nombre : null);
  }, [empresa_id, empresas, profile]);

  const totalChunks = useMemo(
    () => docs.reduce((sum, d) => sum + d.chunks, 0),
    [docs],
  );

  useEffect(() => {
    let cancelled = false;

    const loadEmpresas = async () => {
      if (isPlatformOwner) {
        const { data } = await supabase.from('empresas').select('id, nombre').order('nombre');
        if (cancelled) return;
        setEmpresas((data || []) as Empresa[]);
        setSelectedEmpresaId(prev => prev ?? (data?.length ? Number(data[0].id) : null));
      } else {
        setSelectedEmpresaId(profile?.empresa_id ?? null);
      }
    };

    loadEmpresas();
    return () => { cancelled = true; };
  }, [isPlatformOwner, profile?.empresa_id]);

  const load = useCallback(async () => {
    if (!empresa_id) {
      setDocs([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const params = `?empresa_id=${empresa_id}`;
      const res = await fetch(`${API_BASE}/api/knowledge/${params}`, { headers });
      if (res.ok) setDocs(await res.json());
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [empresa_id, token]);

  useEffect(() => { load(); }, [load]);

  const loadCompanyContext = useCallback(async () => {
    if (!empresa_id) {
      setCompanyContext('');
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/api/knowledge/company-context?empresa_id=${empresa_id}`, { headers });
      if (res.ok) {
        const data = await res.json();
        setCompanyContext(data.company_context || '');
      }
    } catch (e) {
      console.error(e);
    }
  }, [empresa_id, token]);

  useEffect(() => { loadCompanyContext(); }, [loadCompanyContext]);

  const saveCompanyContext = async () => {
    if (!empresa_id) return;
    setSavingContext(true);
    try {
      const res = await fetch(`${API_BASE}/api/knowledge/company-context`, {
        method: 'PUT',
        headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({ empresa_id, company_context: companyContext }),
      });
      if (res.ok) flash('ok', 'Contexto de empresa guardado');
      else flash('error', 'No se pudo guardar el contexto');
    } catch (e) {
      flash('error', String(e));
    } finally {
      setSavingContext(false);
    }
  };

  const generateCompanyContext = async () => {
    if (!empresa_id) return;
    setGeneratingContext(true);
    try {
      const res = await fetch(`${API_BASE}/api/ai/company-context`, {
        method: 'POST',
        headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({ empresa_id }),
      });
      const data = await res.json();
      if (res.ok && data.success) {
        setCompanyContext(data.company_context || '');
        flash('ok', 'Contexto generado — recuerda guardar');
      } else {
        flash('error', data.error || 'Error al generar contexto');
      }
    } catch (e) {
      flash('error', String(e));
    } finally {
      setGeneratingContext(false);
    }
  };

  const flash = (type: 'ok' | 'error', text: string) => {
    setMsg({ type, text });
    setTimeout(() => setMsg(null), 5000);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) applyFile(file);
  };

  const applyFile = (file: File) => {
    setUploadFile(file);
    if (!uploadTitle) {
      setUploadTitle(file.name.replace(/\.[^.]+$/, ''));
    }
    const ext = file.name.split('.').pop()?.toLowerCase();
    if (ext === 'pdf') setUploadType('pdf');
    else if (ext === 'md') setUploadType('manual');
  };

  const handleUpload = async () => {
    if (!uploadFile || !uploadTitle.trim() || !empresa_id) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append('file', uploadFile);
      fd.append('titulo', uploadTitle.trim());
      fd.append('source_type', uploadType);
      fd.append('empresa_id', String(empresa_id));

      const res = await fetch(`${API_BASE}/api/knowledge/upload`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: fd,
      });
      if (res.ok) {
        const data = await res.json();
        flash('ok', `"${data.titulo}" indexado — ${data.chunks_total} chunks`);
        setUploadFile(null);
        setUploadTitle('');
        await load();
      } else {
        const err = await res.json().catch(() => ({}));
        flash('error', err.detail || 'Error al indexar documento');
      }
    } catch (e) {
      flash('error', String(e));
    } finally {
      setUploading(false);
    }
  };

  const handleUploadUrl = async () => {
    if (!urlInput.trim() || !urlTitle.trim() || !empresa_id) return;
    setUploadingUrl(true);
    try {
      const fd = new FormData();
      fd.append('url', urlInput.trim());
      fd.append('titulo', urlTitle.trim());
      fd.append('source_type', 'web');
      fd.append('empresa_id', String(empresa_id));

      const res = await fetch(`${API_BASE}/api/knowledge/upload-url`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: fd,
      });
      if (res.ok) {
        const data = await res.json();
        flash('ok', `URL "${data.titulo}" indexada — ${data.chunks_total} chunks`);
        setUrlInput('');
        setUrlTitle('');
        await load();
      } else {
        const err = await res.json().catch(() => ({}));
        flash('error', err.detail || 'Error al indexar URL');
      }
    } catch (e) {
      flash('error', String(e));
    } finally {
      setUploadingUrl(false);
    }
  };

  const handleDelete = async (titulo: string) => {
    if (!confirm(`¿Eliminar todos los chunks de "${titulo}"?`)) return;
    setDeletingTitle(titulo);
    try {
      const params = empresa_id ? `?empresa_id=${empresa_id}` : '';
      const res = await fetch(
        `${API_BASE}/api/knowledge/${encodeURIComponent(titulo)}${params}`,
        { method: 'DELETE', headers },
      );
      if (res.ok || res.status === 204) {
        flash('ok', `"${titulo}" eliminado`);
        await load();
      } else {
        flash('error', 'Error al eliminar');
      }
    } catch (e) {
      flash('error', String(e));
    } finally {
      setDeletingTitle(null);
    }
  };

  const handleSearch = async () => {
    if (!searchQ.trim() || !empresa_id) return;
    setSearching(true);
    setSearchResults([]);
    try {
      const params = new URLSearchParams({
        q: searchQ.trim(),
        threshold: String(searchThreshold),
        limit: '8',
        empresa_id: String(empresa_id),
      });
      const res = await fetch(`${API_BASE}/api/knowledge/search?${params}`, { headers });
      if (res.ok) {
        const data = await res.json();
        setSearchResults(data.results || []);
        if (!data.results?.length) flash('ok', 'No hay resultados con ese umbral de similitud');
      } else {
        flash('error', 'Error en búsqueda');
      }
    } catch (e) {
      flash('error', String(e));
    } finally {
      setSearching(false);
    }
  };

  const docIcon = (type: string) => {
    if (type === 'web') return 'language';
    if (type === 'pdf') return 'description';
    if (type === 'faq') return 'quiz';
    return 'article';
  };

  return (
    <div className="kb-page relative min-h-full">
      <div className="pointer-events-none absolute top-0 right-0 h-[420px] w-[420px] rounded-full bg-emerald-500/5 blur-[100px]" />
      <div className="pointer-events-none absolute bottom-0 left-0 h-[360px] w-[360px] rounded-full bg-cyan-500/5 blur-[90px]" />

      <div className="relative z-10 mx-auto max-w-7xl space-y-6">
        {/* Empresa selector */}
        <div className="kb-empresa-bar flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-indigo-500/15 text-indigo-600 dark:text-indigo-300">
              <Building2 size={22} />
            </div>
            <div>
              <p className="kb-mono text-xs font-bold uppercase tracking-widest text-indigo-600/80 dark:text-indigo-300/90">
                Empresas
              </p>
              <p className="text-sm font-semibold text-gray-900 dark:text-white">
                {selectedEmpresaName || (isPlatformOwner ? 'Selecciona una empresa' : 'Tu empresa')}
              </p>
              {empresa_id && (
                <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
                  Conocimiento compartido por todos los agentes de esta empresa
                </p>
              )}
            </div>
          </div>
          {isPlatformOwner ? (
            <select
              value={selectedEmpresaId || ''}
              onChange={e => setSelectedEmpresaId(e.target.value ? Number(e.target.value) : null)}
              className="kb-empresa-bar__select"
            >
              <option value="">Selecciona empresa</option>
              {empresas.map(emp => (
                <option key={emp.id} value={emp.id}>{emp.nombre}</option>
              ))}
            </select>
          ) : null}
        </div>

        {/* Breadcrumb */}
        <div className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400">
          <span>Operaciones</span>
          <MaterialIcon name="chevron_right" className="!text-base opacity-60" />
          <span className="font-medium text-gray-900 dark:text-gray-100">Base de Conocimiento</span>
          {selectedEmpresaName && (
            <>
              <MaterialIcon name="chevron_right" className="!text-base opacity-60" />
              <span className="font-medium text-emerald-600 dark:text-primary">{selectedEmpresaName}</span>
            </>
          )}
        </div>

        {/* Header */}
        <div className="flex flex-col justify-between gap-6 md:flex-row md:items-start">
          <div className="space-y-2">
            <div className="flex items-center gap-4">
              <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-500 to-cyan-600 shadow-lg shadow-emerald-500/20">
                <MaterialIcon name="menu_book" className="!text-2xl text-white" />
              </div>
              <h1 className="text-3xl font-bold tracking-tight text-gray-900 dark:text-white">
                Base de Conocimiento
              </h1>
            </div>
            <p className="ml-16 max-w-2xl text-base text-gray-500 dark:text-gray-400">
              Información de la empresa, datos de clientes, catálogos, políticas o cualquier documento útil para las llamadas.
              Lo consultan <strong className="font-semibold text-gray-700 dark:text-gray-200">todos los agentes</strong> de{' '}
              {selectedEmpresaName || 'la empresa'}.
            </p>
          </div>

          <div className="flex flex-col items-end gap-2 self-start">
          <div className="kb-glass flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-semibold text-emerald-700 dark:text-primary">
            <Users size={14} />
            <span>Compartido · todos los agentes</span>
          </div>
          <div className="kb-glass flex items-center gap-3 rounded-full px-4 py-2">
            <span className="text-xs font-bold uppercase tracking-widest text-gray-500 dark:text-gray-400">Estado</span>
            <div className="h-4 w-px bg-gray-200 dark:bg-gray-600" />
            <div className="flex items-center gap-2 text-sm font-bold text-emerald-600 dark:text-primary">
              <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-500 dark:bg-primary shadow-[0_0_8px_rgba(78,222,163,0.6)]" />
              {loading ? 'SINCRONIZANDO' : docs.length ? 'SINCRONIZADO' : 'VACÍO'}
            </div>
          </div>
          </div>
        </div>

        {/* Flash */}
        {msg && (
          <div
            className={`kb-glass flex items-center gap-2 rounded-xl px-4 py-3 text-sm ${
              msg.type === 'ok'
                ? 'border-emerald-200 text-emerald-700 dark:border-primary/30 dark:text-primary'
                : 'border-red-200 text-red-700 dark:border-red-500/30 dark:text-red-300'
            }`}
          >
            {msg.type === 'ok' ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />}
            <span>{msg.text}</span>
            <button type="button" onClick={() => setMsg(null)} className="ml-auto opacity-70 hover:opacity-100">
              <X size={14} />
            </button>
          </div>
        )}

        {!empresa_id && (
          <div className="kb-glass rounded-2xl p-10 text-center text-gray-500 dark:text-gray-400">
            Selecciona una empresa para gestionar su base de conocimiento.
          </div>
        )}

        {empresa_id && (
          <>
          <div className="kb-glass rounded-2xl border border-emerald-200/80 bg-emerald-50/60 p-4 dark:border-primary/20 dark:bg-primary/5">
            <div className="flex gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-emerald-100 text-emerald-700 dark:bg-primary/15 dark:text-primary">
                <Users size={20} />
              </div>
              <div className="text-sm text-gray-700 dark:text-gray-300">
                <p className="font-semibold text-gray-900 dark:text-white">
                  Base de conocimiento de {selectedEmpresaName || 'la empresa'}
                </p>
                <p className="mt-1 leading-relaxed text-gray-600 dark:text-gray-400">
                  Sube aquí lo que cualquier agente de la empresa pueda necesitar: quiénes sois, servicios, precios,
                  guías de clientes, incidencias frecuentes, procedimientos internos, etc. No hace falta repetirlo en cada agente.
                  Si un agente necesita documentación solo suya (por ejemplo, un guion de ventas), añádela en{' '}
                  <span className="font-medium text-emerald-700 dark:text-primary">Agentes de voz</span>.
                </p>
              </div>
            </div>
          </div>

          <section className="kb-glass rounded-2xl p-6">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Contexto de empresa</h2>
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  Resumen en texto libre sobre {selectedEmpresaName || 'la empresa'}: qué hace, cómo atiende y qué debe saber cualquier agente.
                </p>
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={generateCompanyContext}
                  disabled={generatingContext}
                  className="rounded-lg border border-primary/30 bg-primary/10 px-3 py-2 text-xs font-semibold text-primary"
                >
                  {generatingContext ? 'Generando…' : 'Autorrellenar'}
                </button>
                <button
                  type="button"
                  onClick={saveCompanyContext}
                  disabled={savingContext}
                  className="rounded-lg bg-primary px-4 py-2 text-xs font-bold text-on-primary"
                >
                  {savingContext ? 'Guardando…' : 'Guardar contexto'}
                </button>
              </div>
            </div>
            <textarea
              value={companyContext}
              onChange={e => setCompanyContext(e.target.value)}
              rows={5}
              placeholder="Ej: somos una clínica dental en Madrid; horario L–V 9–20h; política de cancelación 24h; tono cercano y profesional…"
              className="kb-field w-full rounded-xl px-4 py-3"
            />
          </section>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            {/* Left column */}
            <div className="space-y-6 lg:col-span-2">
              {/* Upload */}
              <section className="kb-glass relative overflow-hidden rounded-2xl p-6">
                <div className="absolute left-0 top-0 h-full w-1 bg-primary" />
                <div className="mb-6 flex items-center justify-between">
                  <div>
                    <h2 className="flex items-center gap-2 text-lg font-semibold text-gray-900 dark:text-white">
                      <MaterialIcon name="upload_file" className="text-emerald-600 dark:text-primary" />
                      Documentos de la empresa
                    </h2>
                    <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                      Manuales, FAQs, fichas de clientes, catálogos, políticas… indexados para toda la empresa.
                    </p>
                  </div>
                  <span className="rounded border border-emerald-200 bg-emerald-50 px-2 py-1 text-[10px] font-bold uppercase tracking-wider text-emerald-700 dark:border-primary/20 dark:bg-gray-800 dark:text-primary">
                    Empresa · todos los agentes
                  </span>
                </div>

                <div
                  role="button"
                  tabIndex={0}
                  onDrop={handleDrop}
                  onDragOver={e => { e.preventDefault(); setDragOver(true); }}
                  onDragLeave={() => setDragOver(false)}
                  onClick={() => fileInputRef.current?.click()}
                  onKeyDown={e => e.key === 'Enter' && fileInputRef.current?.click()}
                  className={`group flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed p-10 text-center transition-all ${
                    dragOver
                      ? 'border-emerald-400 bg-emerald-50 dark:border-primary/60 dark:bg-primary/5'
                      : uploadFile
                        ? 'border-emerald-300 bg-emerald-50 dark:border-primary/40 dark:bg-primary/5'
                        : 'border-gray-300 hover:border-emerald-400 hover:bg-gray-50 dark:border-gray-600 dark:hover:border-primary/50 dark:hover:bg-gray-800/40'
                  }`}
                >
                  <input
                    ref={fileInputRef}
                    type="file"
                    className="hidden"
                    accept={KNOWLEDGE_FILE_ACCEPT}
                    onChange={e => { const f = e.target.files?.[0]; if (f) applyFile(f); }}
                  />
                  <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-gray-100 transition-transform group-hover:scale-110 group-hover:bg-emerald-100 dark:bg-gray-800 dark:group-hover:bg-primary/15">
                    <MaterialIcon
                      name={uploadFile ? 'description' : 'cloud_upload'}
                      className="!text-3xl text-gray-400 group-hover:text-emerald-600 dark:group-hover:text-primary"
                    />
                  </div>
                  {uploadFile ? (
                    <div className="flex items-center gap-2 text-emerald-600 dark:text-primary">
                      <span className="font-semibold">{uploadFile.name}</span>
                      <button
                        type="button"
                        onClick={e => { e.stopPropagation(); setUploadFile(null); }}
                        className="rounded p-1 hover:bg-red-100 hover:text-red-600 dark:hover:bg-red-500/10 dark:hover:text-red-300"
                      >
                        <X size={16} />
                      </button>
                    </div>
                  ) : (
                    <>
                      <h3 className="mb-1 text-lg font-semibold text-gray-900 dark:text-white">Arrastra documentos aquí</h3>
                      <p className="mb-6 text-sm text-gray-500 dark:text-gray-400">
                        PDF, Markdown, TXT, CSV, JSON y Excel hasta 50 MB
                      </p>
                    </>
                  )}
                  <button
                    type="button"
                    onClick={e => { e.stopPropagation(); fileInputRef.current?.click(); }}
                    className="rounded-lg bg-gray-900 px-6 py-2.5 text-sm font-semibold text-white shadow-md transition-colors hover:bg-gray-800 dark:bg-gray-100 dark:text-gray-900 dark:hover:bg-white"
                  >
                    Seleccionar archivos
                  </button>
                </div>

                <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <div>
                    <label className="mb-1.5 block text-xs font-medium text-gray-500 dark:text-gray-400">
                      Título del documento
                    </label>
                    <input
                      type="text"
                      value={uploadTitle}
                      onChange={e => setUploadTitle(e.target.value)}
                      placeholder="Ej: Catálogo productos 2025, FAQ clientes, Política devoluciones…"
                      className="kb-field px-3 py-2.5"
                    />
                  </div>
                  <div>
                    <label className="mb-1.5 block text-xs font-medium text-gray-500 dark:text-gray-400">
                      Tipo de fuente
                    </label>
                    <select
                      value={uploadType}
                      onChange={e => setUploadType(e.target.value)}
                      className="kb-field px-3 py-2.5"
                    >
                      {Object.entries(SOURCE_LABELS).map(([v, l]) => (
                        <option key={v} value={v}>{l}</option>
                      ))}
                    </select>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={handleUpload}
                  disabled={uploading || !uploadFile || !uploadTitle.trim()}
                  className="mt-4 flex items-center justify-center gap-2 rounded-lg bg-primary px-6 py-2.5 text-sm font-semibold text-on-primary transition-colors hover:bg-primary-fixed-dim disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {uploading ? <Loader2 size={16} className="animate-spin" /> : <MaterialIcon name="layers" className="!text-base" />}
                  {uploading ? 'Indexando…' : 'Indexar documento'}
                </button>

                <div className="mt-6 border-t border-gray-200 pt-6 dark:border-gray-700">
                  <h3 className="mb-3 flex items-center gap-2 text-sm font-medium text-gray-500 dark:text-gray-400">
                    <MaterialIcon name="language" className="!text-base text-cyan-500 dark:text-cyan-400" />
                    Añadir fuente desde URL
                  </h3>
                  <div className="flex flex-col gap-3 sm:flex-row">
                    <div className="relative flex-1">
                      <MaterialIcon name="link" className="absolute left-3 top-1/2 -translate-y-1/2 !text-base text-gray-400" />
                      <input
                        type="text"
                        value={urlInput}
                        onChange={e => setUrlInput(e.target.value)}
                        placeholder="https://docs.tuempresa.com/guias/..."
                        className="kb-field py-2.5 pl-9 pr-4"
                      />
                    </div>
                    <input
                      type="text"
                      value={urlTitle}
                      onChange={e => setUrlTitle(e.target.value)}
                      placeholder="Título"
                      className="kb-field px-4 py-2.5 sm:w-48"
                    />
                    <button
                      type="button"
                      onClick={handleUploadUrl}
                      disabled={uploadingUrl || !urlInput.trim() || !urlTitle.trim()}
                      className="flex items-center justify-center gap-2 rounded-lg bg-cyan-600 px-5 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-cyan-500 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      {uploadingUrl ? <Loader2 size={16} className="animate-spin" /> : null}
                      {uploadingUrl ? 'Indexando…' : 'Indexar URL'}
                    </button>
                  </div>
                </div>
              </section>

              {/* Documents table */}
              <section className="kb-glass relative overflow-hidden rounded-2xl p-6">
                <div className="absolute left-0 top-0 h-full w-1 bg-cyan-400" />
                <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h2 className="flex items-center gap-2 text-lg font-semibold text-gray-900 dark:text-white">
                      <MaterialIcon name="layers" className="text-cyan-500 dark:text-cyan-400" />
                      Conocimiento activo de la empresa
                    </h2>
                    <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                      Documentos indexados disponibles para todos los agentes de {selectedEmpresaName || 'la empresa'}.
                    </p>
                  </div>
                  <p className="kb-mono rounded bg-gray-100 px-2 py-1 text-xs text-gray-600 dark:bg-gray-800 dark:text-gray-400">
                    Total chunks: {totalChunks}
                  </p>
                </div>

                {loading ? (
                  <div className="flex items-center justify-center py-16 text-gray-500 dark:text-gray-400">
                    <Loader2 size={24} className="mr-2 animate-spin" />
                    Cargando índice…
                  </div>
                ) : docs.length === 0 ? (
                  <p className="py-12 text-center text-sm text-gray-500 dark:text-gray-400">
                    Aún no hay documentos de empresa. Sube información, clientes o procedimientos que todos los agentes puedan usar.
                  </p>
                ) : (
                  <div className="overflow-x-auto rounded-lg border border-gray-200 bg-gray-50/50 dark:border-gray-700 dark:bg-gray-900/30">
                    <table className="w-full text-left text-sm">
                      <thead className="border-b border-gray-200 bg-gray-100 text-xs uppercase text-gray-500 dark:border-gray-700 dark:bg-gray-800/60 dark:text-gray-400">
                        <tr>
                          <th className="px-4 py-3 font-semibold">Documento</th>
                          <th className="px-4 py-3 font-semibold">Tipo</th>
                          <th className="px-4 py-3 font-semibold">Chunks</th>
                          <th className="px-4 py-3 font-semibold">Fecha</th>
                          <th className="px-4 py-3 text-right font-semibold">Acciones</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                        {docs.map(doc => (
                          <tr key={doc.titulo} className="group transition-colors hover:bg-gray-50 dark:hover:bg-gray-800/40">
                            <td className="flex max-w-xs items-center gap-2 px-4 py-3 font-medium text-gray-900 dark:text-gray-100">
                              <MaterialIcon name={docIcon(doc.source_type)} className="!text-base text-gray-400" />
                              <span className="truncate">{doc.titulo}</span>
                            </td>
                            <td className="px-4 py-3">
                              <span className={`rounded border px-2 py-0.5 text-[10px] font-bold uppercase ${sourceBadgeClass(doc.source_type)}`}>
                                {SOURCE_LABELS[doc.source_type] ?? doc.source_type}
                              </span>
                            </td>
                            <td className="kb-mono px-4 py-3 text-gray-500 dark:text-gray-400">{doc.chunks}</td>
                            <td className="px-4 py-3 text-gray-500 dark:text-gray-400">
                              {new Date(doc.created_at).toLocaleDateString('es-ES', {
                                day: 'numeric',
                                month: 'short',
                                year: 'numeric',
                              })}
                            </td>
                            <td className="px-4 py-3 text-right">
                              <button
                                type="button"
                                onClick={() => handleDelete(doc.titulo)}
                                disabled={deletingTitle === doc.titulo}
                                className="rounded p-1 text-gray-400 opacity-0 transition-all hover:bg-red-100 hover:text-red-600 group-hover:opacity-100 disabled:opacity-50 dark:hover:bg-red-500/10 dark:hover:text-red-300"
                                title="Eliminar"
                              >
                                {deletingTitle === doc.titulo
                                  ? <Loader2 size={16} className="animate-spin" />
                                  : <MaterialIcon name="delete" className="!text-base" />}
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            </div>

            {/* Right column — semantic search */}
            <div className="lg:col-span-1">
              <div className="kb-glass relative flex h-full flex-col overflow-hidden rounded-2xl p-6">
                <div className="kb-grid-bg pointer-events-none absolute inset-0" />
                <div className="relative z-10 mb-6">
                  <h2 className="flex items-center gap-2 text-lg font-semibold text-gray-900 dark:text-white">
                    <MaterialIcon name="troubleshoot" className="text-emerald-600 dark:text-primary" />
                    Búsqueda semántica
                  </h2>
                  <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                    Prueba qué encontrarían los agentes al consultar el conocimiento de la empresa.
                  </p>
                </div>

                <div className="relative z-10 flex flex-1 flex-col space-y-4">
                  <div className="relative">
                    <MaterialIcon name="manage_search" className="absolute left-3 top-1/2 -translate-y-1/2 !text-base text-gray-400" />
                    <input
                      type="text"
                      value={searchQ}
                      onChange={e => setSearchQ(e.target.value)}
                      onKeyDown={e => e.key === 'Enter' && handleSearch()}
                      placeholder="Consulta el índice semántico…"
                      className="kb-field py-2.5 pl-10 pr-4 shadow-inner"
                    />
                  </div>

                  <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 dark:border-gray-700 dark:bg-gray-800/40">
                    <div className="mb-2 flex items-center justify-between">
                      <span className="text-xs font-medium text-gray-500 dark:text-gray-400">Umbral de similitud</span>
                      <span className="kb-mono text-xs text-emerald-600 dark:text-primary">{searchThreshold.toFixed(2)}</span>
                    </div>
                    <input
                      type="range"
                      min={0}
                      max={100}
                      value={Math.round(searchThreshold * 100)}
                      onChange={e => setSearchThreshold(Number(e.target.value) / 100)}
                      className="h-1.5 w-full cursor-pointer appearance-none rounded-lg bg-gray-200 accent-emerald-500 dark:bg-gray-700 dark:accent-primary"
                    />
                  </div>

                  <button
                    type="button"
                    onClick={handleSearch}
                    disabled={searching || !searchQ.trim()}
                    className="flex w-full items-center justify-center gap-2 rounded-lg bg-primary/15 py-2.5 text-sm font-semibold text-primary ring-1 ring-primary/30 transition-colors hover:bg-primary/25 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    {searching ? <Loader2 size={16} className="animate-spin" /> : <MaterialIcon name="search" className="!text-base" />}
                    {searching ? 'Buscando…' : 'Buscar'}
                  </button>

                  <div className="mt-2 flex-1 space-y-3">
                    <h3 className="text-xs font-bold uppercase tracking-wider text-gray-500 dark:text-gray-400">
                      Mejores coincidencias
                    </h3>

                    {searchResults.length === 0 && !searching && (
                      <p className="py-6 text-center text-xs italic text-gray-400 dark:text-gray-500">
                        Escribe una consulta para ver chunks semánticos.
                      </p>
                    )}

                    {searchResults.map((r, i) => {
                      const pct = Math.round(r.similarity * 100);
                      const barColor = r.similarity >= 0.9 ? 'bg-emerald-500 dark:bg-primary/80' : r.similarity >= 0.75 ? 'bg-cyan-500 dark:bg-cyan-400/70' : 'bg-gray-300 dark:bg-gray-600';
                      return (
                        <div
                          key={`${r.titulo}-${i}`}
                          className="group relative cursor-pointer overflow-hidden rounded-xl border border-gray-200 bg-white p-3 transition-colors hover:border-emerald-300 dark:border-gray-700 dark:bg-gray-800/60 dark:hover:border-primary/40"
                        >
                          <div className={`absolute left-0 top-0 h-full w-1 ${barColor}`} />
                          <div className="mb-2 flex items-start justify-between pl-2">
                            <div className="flex items-center gap-1 text-xs font-medium text-gray-500 dark:text-gray-400">
                              <MaterialIcon name={docIcon('manual')} className="!text-sm" />
                              <span className="max-w-[140px] truncate">{r.titulo}</span>
                            </div>
                            <span className={`kb-mono rounded border px-1.5 py-0.5 text-[10px] font-medium ${matchColor(r.similarity)}`}>
                              {pct}% match
                            </span>
                          </div>
                          <p className="kb-mono line-clamp-3 pl-2 text-[11px] leading-relaxed text-gray-700 dark:text-gray-200">
                            {r.contenido}
                          </p>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            </div>
          </div>
          </>
        )}
      </div>
    </div>
  );
}

export default KnowledgeBaseView;
