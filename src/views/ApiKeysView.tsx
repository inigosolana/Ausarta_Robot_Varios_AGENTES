import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Key,
  Plus,
  Trash2,
  Copy,
  Check,
  ShieldAlert,
  Loader2,
  AlertTriangle,
  Eye,
  EyeOff,
} from 'lucide-react';
import { toast } from 'react-hot-toast';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../contexts/AuthContext';
import {
  createApiKey,
  fetchApiKeys,
  revokeApiKey,
  type ApiKeyCreateResult,
  type ApiKeyListItem,
  type ApiKeyScope,
} from '../lib/apiKeys';
import { apiFetch } from '../lib/apiFetch';

type EmpresaOption = { id: number; nombre: string };

const SCOPE_LABELS: Record<ApiKeyScope, { label: string; hint: string }> = {
  outbound_call: {
    label: 'Llamadas salientes',
    hint: 'Permite POST /api/calls/outbound (n8n, integraciones)',
  },
  webhook: {
    label: 'Webhooks',
    hint: 'Autenticación en webhooks de integración',
  },
  read: {
    label: 'Solo lectura',
    hint: 'Consultas de lectura (futuro)',
  },
  admin: {
    label: 'Administración',
    hint: 'Acceso amplio — solo superadmin puede crear',
  },
};

const ADMIN_SCOPES: ApiKeyScope[] = ['outbound_call', 'webhook', 'read'];
const SUPERADMIN_SCOPES: ApiKeyScope[] = ['outbound_call', 'webhook', 'read', 'admin'];

function formatDate(value?: string | null): string {
  if (!value) return '—';
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

/** Modal de revelación única: la clave nunca se vuelve a mostrar ni se persiste. */
const KeyRevealModal: React.FC<{
  created: ApiKeyCreateResult;
  onClose: () => void;
}> = ({ created, onClose }) => {
  const [confirmed, setConfirmed] = useState(false);
  const [copied, setCopied] = useState(false);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    return () => {
      // Limpieza defensiva al desmontar (no localStorage/sessionStorage)
      setVisible(false);
      setCopied(false);
    };
  }, []);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(created.key);
      setCopied(true);
      toast.success('Copiada al portapapeles');
      setTimeout(() => setCopied(false), 2500);
    } catch {
      toast.error('No se pudo copiar. Selecciona y copia manualmente.');
    }
  };

  const handleClose = () => {
    if (!confirmed) return;
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
      <div
        className="w-full max-w-lg rounded-2xl border border-amber-200 dark:border-amber-800/60 bg-white dark:bg-slate-900 shadow-2xl"
        role="dialog"
        aria-modal="true"
        aria-labelledby="api-key-reveal-title"
      >
        <div className="p-5 border-b border-amber-100 dark:border-amber-900/40 bg-amber-50 dark:bg-amber-950/30 rounded-t-2xl">
          <div className="flex items-start gap-3">
            <ShieldAlert className="text-amber-600 shrink-0 mt-0.5" size={22} />
            <div>
              <h2 id="api-key-reveal-title" className="font-bold text-amber-900 dark:text-amber-100">
                Guarda esta clave ahora
              </h2>
              <p className="text-sm text-amber-800/90 dark:text-amber-200/80 mt-1">
                Solo se muestra una vez. No se almacena en el navegador ni se puede recuperar después.
              </p>
            </div>
          </div>
        </div>

        <div className="p-5 space-y-4">
          <div>
            <label className="text-xs font-semibold uppercase tracking-wide text-gray-500">
              API Key
            </label>
            <div className="mt-1 flex gap-2">
              <code className="flex-1 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 px-3 py-2 text-sm font-mono break-all select-all">
                {visible ? created.key : '•'.repeat(Math.min(created.key.length, 48))}
              </code>
              <button
                type="button"
                onClick={() => setVisible(v => !v)}
                className="p-2 rounded-lg border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800"
                title={visible ? 'Ocultar' : 'Mostrar'}
              >
                {visible ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
              <button
                type="button"
                onClick={handleCopy}
                className="p-2 rounded-lg border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800"
                title="Copiar"
              >
                {copied ? <Check size={18} className="text-green-600" /> : <Copy size={18} />}
              </button>
            </div>
          </div>

          <p className="text-xs text-gray-500 dark:text-gray-400">
            Prefijo: <span className="font-mono">{created.key_prefix}</span> · Empresa ID: {created.empresa_id}
          </p>

          <label className="flex items-start gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={e => setConfirmed(e.target.checked)}
              className="mt-1"
            />
            <span className="text-sm text-gray-700 dark:text-gray-300">
              He copiado y guardado la clave en un gestor seguro (no en email ni chat).
            </span>
          </label>
        </div>

        <div className="p-5 border-t border-gray-100 dark:border-gray-800 flex justify-end">
          <button
            type="button"
            disabled={!confirmed}
            onClick={handleClose}
            className="px-4 py-2 rounded-lg bg-gray-900 dark:bg-cyan-600 text-white text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Cerrar y descartar
          </button>
        </div>
      </div>
    </div>
  );
};

const RevokeModal: React.FC<{
  item: ApiKeyListItem;
  onCancel: () => void;
  onRevoked: () => void;
}> = ({ item, onCancel, onRevoked }) => {
  const [confirmPrefix, setConfirmPrefix] = useState('');
  const [revoking, setRevoking] = useState(false);

  const canRevoke = confirmPrefix === item.key_prefix;

  const handleRevoke = async () => {
    if (!canRevoke) return;
    setRevoking(true);
    try {
      await revokeApiKey(item.id);
      toast.success('API key revocada');
      onRevoked();
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : 'Error al revocar');
    } finally {
      setRevoking(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50">
      <div className="w-full max-w-md rounded-2xl bg-white dark:bg-slate-900 border border-red-200 dark:border-red-900/50 shadow-xl p-5">
        <div className="flex items-center gap-2 text-red-600 mb-3">
          <AlertTriangle size={20} />
          <h3 className="font-bold">Revocar API key</h3>
        </div>
        <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
          Las integraciones que usen esta clave dejarán de funcionar de inmediato.
          Escribe el prefijo <code className="font-mono bg-gray-100 dark:bg-gray-800 px-1 rounded">{item.key_prefix}</code> para confirmar.
        </p>
        <input
          type="text"
          value={confirmPrefix}
          onChange={e => setConfirmPrefix(e.target.value)}
          placeholder={item.key_prefix}
          className="w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-sm font-mono mb-4"
          autoComplete="off"
          spellCheck={false}
        />
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onCancel} className="px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700">
            Cancelar
          </button>
          <button
            type="button"
            disabled={!canRevoke || revoking}
            onClick={handleRevoke}
            className="px-3 py-2 text-sm rounded-lg bg-red-600 text-white disabled:opacity-40 flex items-center gap-2"
          >
            {revoking && <Loader2 size={14} className="animate-spin" />}
            Revocar
          </button>
        </div>
      </div>
    </div>
  );
};

export const ApiKeysView: React.FC = () => {
  const { profile, realProfile, isRole } = useAuth();
  const { t } = useTranslation();
  const isSuperadmin = isRole('superadmin');
  const effectiveProfile = realProfile || profile;

  const [keys, setKeys] = useState<ApiKeyListItem[]>([]);
  const [empresas, setEmpresas] = useState<EmpresaOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [filterEmpresaId, setFilterEmpresaId] = useState<number | ''>('');
  const [revealResult, setRevealResult] = useState<ApiKeyCreateResult | null>(null);
  const [revokeTarget, setRevokeTarget] = useState<ApiKeyListItem | null>(null);

  const [description, setDescription] = useState('');
  const [targetEmpresaId, setTargetEmpresaId] = useState<number | ''>('');
  const [scopes, setScopes] = useState<ApiKeyScope[]>(['outbound_call']);
  const [expiresAt, setExpiresAt] = useState('');

  const availableScopes = isSuperadmin ? SUPERADMIN_SCOPES : ADMIN_SCOPES;

  const loadKeys = useCallback(async () => {
    setLoading(true);
    try {
      const empresaFilter =
        isSuperadmin && filterEmpresaId !== '' ? Number(filterEmpresaId) : undefined;
      const data = await fetchApiKeys(empresaFilter);
      setKeys(data.filter(k => k.is_active));
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : 'Error cargando API keys');
      setKeys([]);
    } finally {
      setLoading(false);
    }
  }, [filterEmpresaId, isSuperadmin]);

  useEffect(() => {
    if (!isRole('superadmin', 'admin')) return;
    void loadKeys();
  }, [isRole, loadKeys]);

  useEffect(() => {
    if (!isSuperadmin) return;
    void (async () => {
      try {
        const res = await apiFetch('/api/admin/empresas');
        if (res.ok) {
          const data = await res.json();
          setEmpresas(data || []);
        }
      } catch {
        /* ignore */
      }
    })();
  }, [isSuperadmin]);

  useEffect(() => {
    if (!isSuperadmin && effectiveProfile?.empresa_id) {
      setTargetEmpresaId(effectiveProfile.empresa_id);
    }
  }, [effectiveProfile?.empresa_id, isSuperadmin]);

  const empresaName = useMemo(() => {
    const map = new Map(empresas.map(e => [e.id, e.nombre]));
    return (id: number) => map.get(id) || `Empresa ${id}`;
  }, [empresas]);

  const toggleScope = (scope: ApiKeyScope) => {
    setScopes(prev =>
      prev.includes(scope) ? prev.filter(s => s !== scope) : [...prev, scope],
    );
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!description.trim() || scopes.length === 0) {
      toast.error('Descripción y al menos un scope son obligatorios');
      return;
    }

    const empresaId = isSuperadmin
      ? (targetEmpresaId !== '' ? Number(targetEmpresaId) : effectiveProfile?.empresa_id)
      : effectiveProfile?.empresa_id;

    if (!empresaId) {
      toast.error('Selecciona una empresa');
      return;
    }

    setCreating(true);
    try {
      const result = await createApiKey({
        description: description.trim(),
        empresa_id: isSuperadmin ? Number(empresaId) : undefined,
        scopes,
        expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
      });
      setDescription('');
      setExpiresAt('');
      setScopes(['outbound_call']);
      setRevealResult(result);
      await loadKeys();
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : 'Error al crear');
    } finally {
      setCreating(false);
    }
  };

  if (!isRole('superadmin', 'admin')) {
    return (
      <div className="flex items-center justify-center min-h-[50vh] text-gray-500">
        <p>{t('Restricted Access', 'Acceso restringido')}</p>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-8">
      {revealResult && (
        <KeyRevealModal
          created={revealResult}
          onClose={() => setRevealResult(null)}
        />
      )}
      {revokeTarget && (
        <RevokeModal
          item={revokeTarget}
          onCancel={() => setRevokeTarget(null)}
          onRevoked={() => {
            setRevokeTarget(null);
            void loadKeys();
          }}
        />
      )}

      <header className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2 text-gray-900 dark:text-white">
            <Key size={24} className="text-cyan-600" />
            API Keys
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            Claves por empresa para n8n e integraciones. Nunca se almacenan en el navegador.
          </p>
        </div>
        {isSuperadmin && empresas.length > 0 && (
          <select
            value={filterEmpresaId}
            onChange={e => setFilterEmpresaId(e.target.value === '' ? '' : Number(e.target.value))}
            className="text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2"
          >
            <option value="">Todas las empresas</option>
            {empresas.map(e => (
              <option key={e.id} value={e.id}>{e.nombre}</option>
            ))}
          </select>
        )}
      </header>

      <div className="rounded-2xl border border-amber-200 dark:border-amber-900/40 bg-amber-50/80 dark:bg-amber-950/20 p-4 flex gap-3">
        <ShieldAlert className="text-amber-600 shrink-0" size={20} />
        <div className="text-sm text-amber-900 dark:text-amber-100/90">
          <p className="font-semibold">Buenas prácticas</p>
          <ul className="list-disc ml-4 mt-1 space-y-0.5 text-amber-800/90 dark:text-amber-200/80">
            <li>Una clave por integración (n8n, script, partner).</li>
            <li>Usa el scope mínimo necesario.</li>
            <li>Revoca al rotar o si sospechas filtración.</li>
            <li>No compartas por email, Slack ni capturas de pantalla.</li>
          </ul>
        </div>
      </div>

      <form
        onSubmit={handleCreate}
        className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-slate-900/50 p-5 space-y-4"
      >
        <h2 className="font-semibold flex items-center gap-2">
          <Plus size={18} />
          Nueva API key
        </h2>

        <div className="grid sm:grid-cols-2 gap-4">
          <div>
            <label className="text-xs font-medium text-gray-500">Descripción</label>
            <input
              type="text"
              maxLength={200}
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="Ej: n8n orquestador campañas"
              className="mt-1 w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-sm"
              required
            />
          </div>

          {isSuperadmin && (
            <div>
              <label className="text-xs font-medium text-gray-500">Empresa</label>
              <select
                value={targetEmpresaId}
                onChange={e => setTargetEmpresaId(e.target.value === '' ? '' : Number(e.target.value))}
                className="mt-1 w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-sm"
                required
              >
                <option value="">Seleccionar…</option>
                {empresas.map(e => (
                  <option key={e.id} value={e.id}>{e.nombre}</option>
                ))}
              </select>
            </div>
          )}

          <div>
            <label className="text-xs font-medium text-gray-500">Caducidad (opcional)</label>
            <input
              type="datetime-local"
              value={expiresAt}
              onChange={e => setExpiresAt(e.target.value)}
              className="mt-1 w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-sm"
            />
          </div>
        </div>

        <div>
          <label className="text-xs font-medium text-gray-500">Permisos (scopes)</label>
          <div className="mt-2 grid sm:grid-cols-2 gap-2">
            {availableScopes.map(scope => (
              <label
                key={scope}
                className={`flex items-start gap-2 p-3 rounded-lg border cursor-pointer transition-colors ${
                  scopes.includes(scope)
                    ? 'border-cyan-500 bg-cyan-50 dark:bg-cyan-950/30'
                    : 'border-gray-200 dark:border-gray-700'
                }`}
              >
                <input
                  type="checkbox"
                  checked={scopes.includes(scope)}
                  onChange={() => toggleScope(scope)}
                  className="mt-0.5"
                />
                <span>
                  <span className="text-sm font-medium block">{SCOPE_LABELS[scope].label}</span>
                  <span className="text-xs text-gray-500">{SCOPE_LABELS[scope].hint}</span>
                </span>
              </label>
            ))}
          </div>
        </div>

        <button
          type="submit"
          disabled={creating || scopes.length === 0}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-cyan-600 text-white text-sm font-medium disabled:opacity-50"
        >
          {creating ? <Loader2 size={16} className="animate-spin" /> : <Key size={16} />}
          Generar clave
        </button>
      </form>

      <section className="rounded-2xl border border-gray-200 dark:border-gray-800 overflow-hidden">
        <div className="px-5 py-3 border-b border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-slate-900/80">
          <h2 className="font-semibold text-sm">Claves activas</h2>
        </div>

        {loading ? (
          <div className="p-8 flex justify-center">
            <Loader2 className="animate-spin text-gray-400" />
          </div>
        ) : keys.length === 0 ? (
          <p className="p-8 text-center text-sm text-gray-500">No hay API keys activas.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase text-gray-500 border-b border-gray-100 dark:border-gray-800">
                  <th className="px-5 py-3">Prefijo</th>
                  <th className="px-5 py-3">Descripción</th>
                  {isSuperadmin && <th className="px-5 py-3">Empresa</th>}
                  <th className="px-5 py-3">Scopes</th>
                  <th className="px-5 py-3">Último uso</th>
                  <th className="px-5 py-3">Caduca</th>
                  <th className="px-5 py-3 w-12" />
                </tr>
              </thead>
              <tbody>
                {keys.map(k => (
                  <tr key={k.id} className="border-b border-gray-50 dark:border-gray-800/80 hover:bg-gray-50/50 dark:hover:bg-slate-800/30">
                    <td className="px-5 py-3 font-mono text-xs">{k.key_prefix}…</td>
                    <td className="px-5 py-3">{k.description || '—'}</td>
                    {isSuperadmin && (
                      <td className="px-5 py-3">{empresaName(k.empresa_id)}</td>
                    )}
                    <td className="px-5 py-3">
                      <div className="flex flex-wrap gap-1">
                        {k.scopes.map(s => (
                          <span key={s} className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-800 font-mono">
                            {s}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-5 py-3 text-gray-500">{formatDate(k.last_used_at)}</td>
                    <td className="px-5 py-3 text-gray-500">{formatDate(k.expires_at)}</td>
                    <td className="px-5 py-3">
                      <button
                        type="button"
                        onClick={() => setRevokeTarget(k)}
                        className="p-1.5 rounded text-red-600 hover:bg-red-50 dark:hover:bg-red-950/30"
                        title="Revocar"
                      >
                        <Trash2 size={16} />
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
  );
};

export default ApiKeysView;
