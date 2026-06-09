import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Loader2, Plus, Trash2, ExternalLink, FileText, Upload } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import {
  KNOWLEDGE_FILE_ACCEPT,
  KNOWLEDGE_FORMATS_LABEL,
  knowledgeSourceTypeFromFile,
  textFileFromContent,
} from '../../lib/knowledgeUpload';

interface KBDoc {
  titulo: string;
  source_type: string;
  chunks: number;
  created_at: string;
}

const API_BASE = (import.meta as { env?: { VITE_API_URL?: string } }).env?.VITE_API_URL ?? '';

type UploadMode = 'file' | 'text';

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
  const [uploadMode, setUploadMode] = useState<UploadMode>('file');
  const [uploadTitle, setUploadTitle] = useState('');
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [textContent, setTextContent] = useState('');
  const [dragOver, setDragOver] = useState(false);
  const [msg, setMsg] = useState<{ type: 'ok' | 'error'; text: string } | null>(null);
  const [deletingTitle, setDeletingTitle] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const flash = (type: 'ok' | 'error', text: string) => {
    setMsg({ type, text });
    setTimeout(() => setMsg(null), 5000);
  };

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

  const applyFile = (file: File) => {
    setUploadFile(file);
    if (!uploadTitle) {
      setUploadTitle(file.name.replace(/\.[^.]+$/, ''));
    }
  };

  const uploadDocument = async (file: File, titulo: string) => {
    if (!empresaId) return;
    const fd = new FormData();
    fd.append('file', file);
    fd.append('titulo', titulo.trim());
    fd.append('source_type', knowledgeSourceTypeFromFile(file));
    fd.append('empresa_id', String(empresaId));
    fd.append('agent_id', String(agentId));

    const res = await fetch(`${API_BASE}/api/knowledge/upload`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: fd,
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      const detail = err.detail;
      const message = Array.isArray(detail)
        ? detail.map((d: { msg?: string }) => d.msg || '').join(' ')
        : (detail || 'Error al indexar documento');
      throw new Error(message);
    }

    const data = await res.json();
    return data as { titulo: string; chunks_total?: number };
  };

  const handleUpload = async () => {
    if (!uploadTitle.trim() || !empresaId) return;

    let fileToUpload: File | null = uploadFile;
    if (uploadMode === 'text') {
      if (!textContent.trim()) {
        flash('error', 'Escribe el contenido del documento');
        return;
      }
      fileToUpload = textFileFromContent(uploadTitle, textContent);
    }

    if (!fileToUpload) {
      flash('error', 'Selecciona un archivo o pega texto');
      return;
    }

    setUploading(true);
    try {
      const data = await uploadDocument(fileToUpload, uploadTitle);
      flash('ok', `"${data.titulo}" indexado${data.chunks_total ? ` (${data.chunks_total} chunks)` : ''}`);
      setUploadFile(null);
      setUploadTitle('');
      setTextContent('');
      if (fileRef.current) fileRef.current.value = '';
      await load();
    } catch (e) {
      flash('error', e instanceof Error ? e.message : 'Error al subir documento');
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
      if (res.ok || res.status === 204) {
        flash('ok', `"${titulo}" eliminado`);
        await load();
      }
    } finally {
      setDeletingTitle(null);
    }
  };

  const canUpload =
    uploadTitle.trim() &&
    (uploadMode === 'file' ? !!uploadFile : !!textContent.trim());

  return (
    <div className="mt-6 space-y-3 border-t border-gray-100 pt-5 dark:border-white/10">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="agent-mono text-xs font-bold uppercase tracking-widest text-gray-500 dark:text-gray-400">
            Conocimiento del agente
          </p>
          <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
            Documentos RAG solo para este agente: scripts, catálogo, objeciones, guías de venta…
          </p>
          <p className="mt-1 text-[11px] text-gray-400 dark:text-gray-500">
            Formatos: {KNOWLEDGE_FORMATS_LABEL}
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

      {msg && (
        <div
          className={`rounded-lg px-3 py-2 text-xs ${
            msg.type === 'ok'
              ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300'
              : 'bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-300'
          }`}
        >
          {msg.text}
        </div>
      )}

      {loading ? (
        <div className="flex items-center gap-2 text-xs text-gray-400">
          <Loader2 size={14} className="animate-spin" />
          Cargando documentos…
        </div>
      ) : docs.length === 0 ? (
        <p className="rounded-lg border border-dashed border-gray-200 bg-gray-50/80 px-3 py-4 text-xs text-gray-500 dark:border-gray-700 dark:bg-gray-900/30 dark:text-gray-400">
          Sin documentos propios. Sube un archivo o pega texto con información que solo este agente deba usar en llamadas.
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
        <div className="rounded-xl border border-gray-100 bg-gray-50/50 p-4 dark:border-white/5 dark:bg-gray-900/30">
          <div className="mb-3 flex gap-2">
            <button
              type="button"
              onClick={() => setUploadMode('file')}
              className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
                uploadMode === 'file'
                  ? 'bg-cyan-600 text-white'
                  : 'bg-white text-gray-600 border border-gray-200 dark:bg-gray-900 dark:border-gray-700 dark:text-gray-300'
              }`}
            >
              <Upload size={13} />
              Archivo
            </button>
            <button
              type="button"
              onClick={() => setUploadMode('text')}
              className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
                uploadMode === 'text'
                  ? 'bg-cyan-600 text-white'
                  : 'bg-white text-gray-600 border border-gray-200 dark:bg-gray-900 dark:border-gray-700 dark:text-gray-300'
              }`}
            >
              <FileText size={13} />
              Texto directo
            </button>
          </div>

          <input
            type="text"
            value={uploadTitle}
            onChange={e => setUploadTitle(e.target.value)}
            placeholder="Título del documento (ej: Script ventas Q2)"
            className="mb-3 w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-900"
          />

          {uploadMode === 'file' ? (
            <>
              <div
                role="button"
                tabIndex={0}
                onDrop={e => {
                  e.preventDefault();
                  setDragOver(false);
                  const file = e.dataTransfer.files[0];
                  if (file) applyFile(file);
                }}
                onDragOver={e => { e.preventDefault(); setDragOver(true); }}
                onDragLeave={() => setDragOver(false)}
                onClick={() => fileRef.current?.click()}
                onKeyDown={e => e.key === 'Enter' && fileRef.current?.click()}
                className={`mb-3 cursor-pointer rounded-lg border-2 border-dashed px-4 py-6 text-center transition-colors ${
                  dragOver
                    ? 'border-cyan-400 bg-cyan-50 dark:bg-cyan-950/30'
                    : uploadFile
                      ? 'border-cyan-300 bg-cyan-50/50 dark:border-cyan-700 dark:bg-cyan-950/20'
                      : 'border-gray-200 hover:border-cyan-300 hover:bg-gray-50 dark:border-gray-700 dark:hover:border-cyan-700'
                }`}
              >
                <input
                  ref={fileRef}
                  type="file"
                  accept={KNOWLEDGE_FILE_ACCEPT}
                  className="hidden"
                  onChange={e => {
                    const f = e.target.files?.[0];
                    if (f) applyFile(f);
                  }}
                />
                {uploadFile ? (
                  <p className="text-sm font-medium text-cyan-700 dark:text-cyan-300">{uploadFile.name}</p>
                ) : (
                  <>
                    <p className="text-sm font-medium text-gray-700 dark:text-gray-200">
                      Arrastra un archivo o haz clic para elegir
                    </p>
                    <p className="mt-1 text-[11px] text-gray-400">{KNOWLEDGE_FORMATS_LABEL}</p>
                  </>
                )}
              </div>
            </>
          ) : (
            <textarea
              value={textContent}
              onChange={e => setTextContent(e.target.value)}
              rows={6}
              placeholder="Pega aquí el contenido: guion de llamada, argumentario, lista de precios, FAQs del producto…"
              className="mb-3 w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm font-mono leading-relaxed dark:border-gray-700 dark:bg-gray-900"
            />
          )}

          <button
            type="button"
            onClick={handleUpload}
            disabled={uploading || !canUpload}
            className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-cyan-600 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-cyan-500 disabled:opacity-50 sm:w-auto"
          >
            {uploading ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
            {uploading ? 'Indexando…' : 'Añadir al agente'}
          </button>
        </div>
      )}
    </div>
  );
};
