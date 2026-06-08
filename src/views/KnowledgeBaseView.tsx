import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  BookOpen,
  FileText,
  Layers,
  Search,
  Trash2,
  Upload,
  X,
  CheckCircle2,
  AlertCircle,
  Loader2,
} from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { supabase } from '../lib/supabase';
import type { Empresa } from '../types';

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

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '';

export function KnowledgeBaseView() {
  const { session, profile, isPlatformOwner } = useAuth();
  const token = session?.access_token ?? '';
  const [empresas, setEmpresas] = useState<Empresa[]>([]);
  const [selectedEmpresaId, setSelectedEmpresaId] = useState<number | null>(profile?.empresa_id ?? null);
  const empresa_id = isPlatformOwner ? selectedEmpresaId : profile?.empresa_id ?? null;

  const [docs, setDocs] = useState<KBDoc[]>([]);
  const [loading, setLoading] = useState(true);
  const [msg, setMsg] = useState<{ type: 'ok' | 'error'; text: string } | null>(null);

  // Upload state
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadTitle, setUploadTitle] = useState('');
  const [uploadType, setUploadType] = useState('manual');
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [urlInput, setUrlInput] = useState('');
  const [urlTitle, setUrlTitle] = useState('');
  const [uploadingUrl, setUploadingUrl] = useState(false);

  // Search state
  const [searchQ, setSearchQ] = useState('');
  const [searching, setSearching] = useState(false);
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searchThreshold, setSearchThreshold] = useState(0.7);

  // Delete
  const [deletingTitle, setDeletingTitle] = useState<string | null>(null);

  const headers = { Authorization: `Bearer ${token}` };

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
    return () => {
      cancelled = true;
    };
  }, [isPlatformOwner, profile?.empresa_id]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = empresa_id ? `?empresa_id=${empresa_id}` : '';
      const res = await fetch(`${API_BASE}/api/knowledge/${params}`, { headers });
      if (res.ok) setDocs(await res.json());
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [empresa_id, token]);

  useEffect(() => { load(); }, [load]);

  const flash = (type: 'ok' | 'error', text: string) => {
    setMsg({ type, text });
    setTimeout(() => setMsg(null), 5000);
  };

  // ─── Upload ───────────────────────────────────────────────────────────────

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
  };

  const handleUpload = async () => {
    if (!uploadFile || !uploadTitle.trim()) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append('file', uploadFile);
      fd.append('titulo', uploadTitle.trim());
      fd.append('source_type', uploadType);
      if (empresa_id) fd.append('empresa_id', String(empresa_id));

      const res = await fetch(`${API_BASE}/api/knowledge/upload`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: fd,
      });
      if (res.ok) {
        const data = await res.json();
        flash('ok', `✓ "${data.titulo}" indexado — ${data.chunks_total} chunks, ${data.chunks_con_embedding} con embedding`);
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
    if (!urlInput.trim() || !urlTitle.trim()) return;
    setUploadingUrl(true);
    try {
      const fd = new FormData();
      fd.append('url', urlInput.trim());
      fd.append('titulo', urlTitle.trim());
      fd.append('source_type', 'web');
      if (empresa_id) fd.append('empresa_id', String(empresa_id));

      const res = await fetch(`${API_BASE}/api/knowledge/upload-url`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: fd,
      });
      if (res.ok) {
        const data = await res.json();
        flash('ok', `✓ URL "${data.titulo}" indexada — ${data.chunks_total} chunks`);
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

  // ─── Delete ───────────────────────────────────────────────────────────────

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

  // ─── Semantic Search ──────────────────────────────────────────────────────

  const handleSearch = async () => {
    if (!searchQ.trim()) return;
    setSearching(true);
    setSearchResults([]);
    try {
      const params = new URLSearchParams({ q: searchQ.trim(), threshold: String(searchThreshold), limit: '8' });
      if (empresa_id) params.set('empresa_id', String(empresa_id));
      const res = await fetch(`${API_BASE}/api/knowledge/search?${params}`, { headers });
      if (res.ok) {
        const data = await res.json();
        setSearchResults(data.results || []);
        if (!data.results?.length) flash('ok', 'No se encontraron resultados para ese umbral');
      } else {
        flash('error', 'Error en búsqueda');
      }
    } catch (e) {
      flash('error', String(e));
    } finally {
      setSearching(false);
    }
  };

  // ─── UI ───────────────────────────────────────────────────────────────────

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-indigo-100 rounded-lg">
            <BookOpen size={24} className="text-indigo-600" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Base de Conocimiento</h1>
            <p className="text-sm text-gray-500">Documentos indexados para búsqueda semántica RAG</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {isPlatformOwner && (
            <select
              value={selectedEmpresaId || ''}
              onChange={(e) => setSelectedEmpresaId(e.target.value ? Number(e.target.value) : null)}
              className="h-9 rounded-lg border border-gray-200 bg-white px-3 text-sm text-gray-700"
            >
              <option value="">Selecciona empresa</option>
              {empresas.map(emp => (
                <option key={emp.id} value={emp.id}>{emp.nombre}</option>
              ))}
            </select>
          )}
          <div className="flex items-center gap-2 px-3 py-1.5 bg-indigo-50 rounded-full">
            <Layers size={16} className="text-indigo-600" />
            <span className="text-sm font-medium text-indigo-700">{docs.length} documentos</span>
          </div>
        </div>
      </div>

      {/* Flash */}
      {msg && (
        <div className={`flex items-center gap-2 px-4 py-3 rounded-lg text-sm ${
          msg.type === 'ok'
            ? 'bg-green-50 text-green-700 border border-green-200'
            : 'bg-red-50 text-red-700 border border-red-200'
        }`}>
          {msg.type === 'ok' ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />}
          <span>{msg.text}</span>
          <button onClick={() => setMsg(null)} className="ml-auto">
            <X size={14} />
          </button>
        </div>
      )}

      {/* Upload Card */}
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
        <h2 className="text-base font-semibold text-gray-800 mb-4 flex items-center gap-2">
          <Upload size={18} className="text-indigo-500" /> Indexar Documento
        </h2>

        {/* Drop Zone */}
        <div
          onDrop={handleDrop}
          onDragOver={e => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onClick={() => fileInputRef.current?.click()}
          className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
            dragOver
              ? 'border-indigo-400 bg-indigo-50'
              : uploadFile
              ? 'border-green-400 bg-green-50'
              : 'border-gray-200 hover:border-indigo-300 hover:bg-gray-50'
          }`}
        >
          <input
            ref={fileInputRef}
            type="file"
            className="hidden"
            accept=".txt,.md,.pdf,.csv,.json,.xlsx,.xls"
            onChange={e => { const f = e.target.files?.[0]; if (f) applyFile(f); }}
          />
          {uploadFile ? (
            <div className="flex items-center justify-center gap-2 text-green-700">
              <FileText size={20} />
              <span className="font-medium">{uploadFile.name}</span>
              <button
                onClick={e => { e.stopPropagation(); setUploadFile(null); }}
                className="ml-2 text-gray-400 hover:text-red-500"
              >
                <X size={16} />
              </button>
            </div>
          ) : (
            <>
              <Upload size={32} className="mx-auto mb-2 text-gray-300" />
              <p className="text-sm text-gray-500">Arrastra un archivo de conocimiento aquí</p>
              <p className="text-xs text-gray-400 mt-1">Formatos: .txt · .md · .pdf · .csv · .json · .xlsx · .xls</p>
            </>
          )}
        </div>

        {/* Fields */}
        <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="text-xs font-medium text-gray-600 mb-1 block">Título del documento</label>
            <input
              type="text"
              value={uploadTitle}
              onChange={e => setUploadTitle(e.target.value)}
              placeholder="Ej: Manual de Instalación v2"
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
            />
          </div>
          <div>
            <label className="text-xs font-medium text-gray-600 mb-1 block">Tipo de fuente</label>
            <select
              value={uploadType}
              onChange={e => setUploadType(e.target.value)}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
            >
              {Object.entries(SOURCE_LABELS).map(([v, l]) => (
                <option key={v} value={v}>{l}</option>
              ))}
            </select>
          </div>
        </div>

        <button
          onClick={handleUpload}
          disabled={uploading || !uploadFile || !uploadTitle.trim()}
          className="mt-4 w-full sm:w-auto flex items-center justify-center gap-2 px-6 py-2.5 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {uploading ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />}
          {uploading ? 'Indexando…' : 'Indexar'}
        </button>

        <div className="mt-6 border-t border-gray-100 pt-4">
          <h3 className="text-sm font-semibold text-gray-800 mb-3">Añadir contenido desde URL</h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <input
              type="text"
              value={urlInput}
              onChange={e => setUrlInput(e.target.value)}
              placeholder="https://..."
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
            />
            <input
              type="text"
              value={urlTitle}
              onChange={e => setUrlTitle(e.target.value)}
              placeholder="Título para esta URL"
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
            />
          </div>
          <button
            onClick={handleUploadUrl}
            disabled={uploadingUrl || !urlInput.trim() || !urlTitle.trim()}
            className="mt-3 flex items-center justify-center gap-2 px-4 py-2 bg-sky-600 text-white text-sm font-medium rounded-lg hover:bg-sky-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {uploadingUrl ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />}
            {uploadingUrl ? 'Indexando URL…' : 'Add URL'}
          </button>
        </div>
      </div>

      {/* Document List */}
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
        <h2 className="text-base font-semibold text-gray-800 mb-4 flex items-center gap-2">
          <FileText size={18} className="text-indigo-500" /> Documentos Indexados
        </h2>
        {loading ? (
          <div className="flex items-center justify-center py-10 text-gray-400">
            <Loader2 size={24} className="animate-spin mr-2" /> Cargando…
          </div>
        ) : docs.length === 0 ? (
          <p className="text-center text-gray-400 py-8 text-sm">No hay documentos indexados aún</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs font-medium text-gray-500 uppercase tracking-wide border-b border-gray-100">
                  <th className="pb-2 pr-4">Título</th>
                  <th className="pb-2 pr-4">Tipo</th>
                  <th className="pb-2 pr-4">Chunks</th>
                  <th className="pb-2 pr-4">Fecha</th>
                  <th className="pb-2"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {docs.map(doc => (
                  <tr key={doc.titulo} className="hover:bg-gray-50">
                    <td className="py-3 pr-4 font-medium text-gray-800 max-w-xs truncate">
                      {doc.titulo}
                    </td>
                    <td className="py-3 pr-4">
                      <span className="px-2 py-0.5 bg-indigo-50 text-indigo-700 rounded-full text-xs font-medium">
                        {SOURCE_LABELS[doc.source_type] ?? doc.source_type}
                      </span>
                    </td>
                    <td className="py-3 pr-4 text-gray-600">{doc.chunks}</td>
                    <td className="py-3 pr-4 text-gray-500">
                      {new Date(doc.created_at).toLocaleDateString('es-ES')}
                    </td>
                    <td className="py-3 text-right">
                      <button
                        onClick={() => handleDelete(doc.titulo)}
                        disabled={deletingTitle === doc.titulo}
                        className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors disabled:opacity-40"
                        title="Eliminar"
                      >
                        {deletingTitle === doc.titulo
                          ? <Loader2 size={15} className="animate-spin" />
                          : <Trash2 size={15} />}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Semantic Search Test */}
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
        <h2 className="text-base font-semibold text-gray-800 mb-4 flex items-center gap-2">
          <Search size={18} className="text-indigo-500" /> Probar Búsqueda Semántica
        </h2>

        <div className="flex gap-3">
          <input
            type="text"
            value={searchQ}
            onChange={e => setSearchQ(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleSearch()}
            placeholder="Escribe una pregunta o frase…"
            className="flex-1 border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
          />
          <div className="flex items-center gap-2 text-xs text-gray-500 whitespace-nowrap">
            <label htmlFor="threshold">Umbral:</label>
            <input
              id="threshold"
              type="number"
              min={0} max={1} step={0.05}
              value={searchThreshold}
              onChange={e => setSearchThreshold(parseFloat(e.target.value) || 0.7)}
              className="w-16 border border-gray-200 rounded px-2 py-1 text-xs text-center"
            />
          </div>
          <button
            onClick={handleSearch}
            disabled={searching || !searchQ.trim()}
            className="flex items-center gap-1.5 px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {searching ? <Loader2 size={15} className="animate-spin" /> : <Search size={15} />}
            Buscar
          </button>
        </div>

        {searchResults.length > 0 && (
          <div className="mt-4 space-y-3">
            {searchResults.map((r, i) => (
              <div key={i} className="border border-gray-100 rounded-lg p-4 bg-gray-50">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs font-semibold text-indigo-700">{r.titulo}</span>
                  <span className="text-xs text-gray-500 bg-white px-2 py-0.5 rounded-full border border-gray-200">
                    {(r.similarity * 100).toFixed(1)}% similitud
                  </span>
                </div>
                <p className="text-sm text-gray-700 leading-relaxed line-clamp-5">{r.contenido}</p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default KnowledgeBaseView;
