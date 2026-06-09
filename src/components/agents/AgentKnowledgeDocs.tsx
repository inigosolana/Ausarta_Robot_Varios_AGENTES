import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Loader2, Plus, Trash2, ExternalLink } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';

interface KBDoc {
  titulo: string;
  source_type: string;
  chunks: number;
  created_at: string;
}

const API_BASE = (import.meta as { env?: { VITE_API_URL?: string } }).env?.VITE_API_URL ?? '';

type Props = {
  agentId: number;
  empresaId?: number | null;
  isEditing: boolean;
};

export const AgentKnowledgeDocs: React.FC<Props> = ({ agentId, empresaId, isEditing }) => {
  const { session } = useAuth();
  const token = session?.access_token ?? '';
  const headers = { Authorization: `Bearer ${token}` };

  const [docs, setDocs] = useState<KBDoc[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [uploadTitle, setUploadTitle] = useState('');
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [deletingTitle, setDeletingTitle] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    if (!empresaId || !agentId) {
      setDocs([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const params = new URLSearchParams({
        empresa_id: String(empresaId),
        agent_id: String(agentId),
      });
      const res = await fetch(`${API_BASE}/api/knowledge/?${params}`, { headers });
      if (res.ok) setDocs(await res.json());
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [agentId, empresaId, token]);

  useEffect(() => { load(); }, [load]);

  const handleUpload = async () => {
    if (!uploadFile || !uploadTitle.trim() || !empresaId) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append('file', uploadFile);
      fd.append('titulo', uploadTitle.trim());
      fd.append('source_type', uploadFile.name.endsWith('.pdf') ? 'pdf' : 'manual');
      fd.append('empresa_id', String(empresaId));
      fd.append('agent_id', String(agentId));
      const res = await fetch(`${API_BASE}/api/knowledge/upload`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: fd,
      });
      if (res.ok) {
        setUploadFile(null);
        setUploadTitle('');
        await load();
      } else {
        const err = await res.json().catch(() => ({}));
        alert(err.detail || 'Error al subir documento');
      }
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async (titulo: string) => {
    if (!confirm(`¿Eliminar "${titulo}" de este agente?`)) return;
    setDeletingTitle(titulo);
    try {
      const params = new URLSearchParams({
        empresa_id: String(empresaId),
        agent_id: String(agentId),
      });
      const res = await fetch(
        `${API_BASE}/api/knowledge/${encodeURIComponent(titulo)}?${params}`,
        { method: 'DELETE', headers },
      );
      if (res.ok || res.status === 204) await load();
    } finally {
      setDeletingTitle(null);
    }
  };

  return (
    <div className="mt-6 space-y-3 border-t border-gray-100 pt-5 dark:border-white/10">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="agent-mono text-xs font-bold uppercase tracking-widest text-gray-500 dark:text-gray-400">
            Conocimiento del agente
          </p>
          <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
            Documentos RAG solo para este agente (ventas, scripts, catálogo…).
          </p>
        </div>
        <Link
          to="/knowledge"
          className="inline-flex items-center gap-1 text-xs font-medium text-cyan-600 hover:text-cyan-500 dark:text-cyan-400"
        >
          Base de empresa
          <ExternalLink size={12} />
        </Link>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 text-xs text-gray-400">
          <Loader2 size={14} className="animate-spin" />
          Cargando documentos…
        </div>
      ) : docs.length === 0 ? (
        <p className="rounded-lg border border-dashed border-gray-200 bg-gray-50/80 px-3 py-4 text-xs text-gray-500 dark:border-gray-700 dark:bg-gray-900/30 dark:text-gray-400">
          Sin documentos propios. Sube PDF o texto con información específica de este agente.
        </p>
      ) : (
        <div className="space-y-2">
          {docs.map(doc => (
            <div
              key={`${doc.titulo}-${doc.source_type}`}
              className="flex items-center justify-between rounded-lg border border-gray-100 bg-gray-50/80 px-3 py-2 dark:border-white/5 dark:bg-gray-900/40"
            >
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-gray-800 dark:text-gray-200">{doc.titulo}</p>
                <p className="agent-mono text-[10px] uppercase text-gray-500">
                  {doc.source_type} · {doc.chunks} chunks
                </p>
              </div>
              {isEditing && (
                <button
                  type="button"
                  onClick={() => handleDelete(doc.titulo)}
                  disabled={deletingTitle === doc.titulo}
                  className="rounded p-1.5 text-gray-400 hover:text-red-500"
                >
                  {deletingTitle === doc.titulo ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : (
                    <Trash2 size={14} />
                  )}
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {isEditing && (
        <div className="rounded-xl border border-gray-100 bg-gray-50/50 p-3 dark:border-white/5 dark:bg-gray-900/30">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
            <input
              type="text"
              value={uploadTitle}
              onChange={e => setUploadTitle(e.target.value)}
              placeholder="Título del documento"
              className="flex-1 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-900"
            />
            <input
              ref={fileRef}
              type="file"
              accept=".pdf,.txt,.md,.csv"
              className="hidden"
              onChange={e => {
                const f = e.target.files?.[0];
                if (f) {
                  setUploadFile(f);
                  if (!uploadTitle) setUploadTitle(f.name.replace(/\.[^.]+$/, ''));
                }
              }}
            />
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-900"
            >
              {uploadFile ? uploadFile.name : 'Elegir archivo'}
            </button>
            <button
              type="button"
              onClick={handleUpload}
              disabled={uploading || !uploadFile || !uploadTitle.trim()}
              className="inline-flex items-center justify-center gap-1 rounded-lg bg-cyan-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
            >
              {uploading ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
              Añadir
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
