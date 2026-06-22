/**
 * WorkflowEditor.tsx
 * ------------------
 * Editor visual de workflows de agente de voz.
 * Usa @xyflow/react para el lienzo drag-and-drop.
 *
 * Props:
 *   value    – WorkflowDefinition actual (o null si vacío)
 *   onChange – callback al modificar el workflow
 *   mode     – "workflow" | "mixed"
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ReactFlow,
  Controls,
  Background,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
  type Connection,
  type Edge,
  type Node,
  type NodeTypes,
  Handle,
  Position,
  Panel,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import type { WorkflowDefinition, WorkflowEdge, WorkflowNode, WorkflowNodeType } from '../types';
import { Plus, X, AlertTriangle, CheckCircle } from 'lucide-react';

// ── Colores por tipo de nodo ─────────────────────────────────────────────────
const NODE_COLORS: Record<WorkflowNodeType, { bg: string; border: string; badge: string; text: string }> = {
  message:   { bg: 'bg-blue-50',   border: 'border-blue-300',   badge: 'bg-blue-500',   text: 'text-blue-800' },
  question:  { bg: 'bg-purple-50', border: 'border-purple-300', badge: 'bg-purple-500', text: 'text-purple-800' },
  condition: { bg: 'bg-amber-50',  border: 'border-amber-300',  badge: 'bg-amber-500',  text: 'text-amber-800' },
  llm_free:  { bg: 'bg-emerald-50',border: 'border-emerald-300',badge: 'bg-emerald-500',text: 'text-emerald-800' },
  schedule:  { bg: 'bg-teal-50',  border: 'border-teal-300',   badge: 'bg-teal-500',   text: 'text-teal-800' },
  transfer:  { bg: 'bg-orange-50', border: 'border-orange-300', badge: 'bg-orange-500', text: 'text-orange-800' },
  end:       { bg: 'bg-gray-100',  border: 'border-gray-400',   badge: 'bg-gray-500',   text: 'text-gray-700' },
};

const NODE_LABELS: Record<WorkflowNodeType, string> = {
  message:   'Mensaje',
  question:  'Pregunta',
  condition: 'Condición',
  llm_free:  'LLM libre',
  schedule:  'Programar',
  transfer:  'Transferir',
  end:       'Fin',
};

const NODE_ICONS: Record<WorkflowNodeType, string> = {
  message:   '💬',
  question:  '❓',
  condition: '🔀',
  llm_free:  '🤖',
  schedule:  '📅',
  transfer:  '📞',
  end:       '🏁',
};

// ── Custom node component ─────────────────────────────────────────────────────
interface WorkflowNodeData {
  label: string;
  type: WorkflowNodeType;
  content?: string;
  prompt?: string;
  variable?: string;
  delay_days?: number;
  isStart?: boolean;
  hasError?: boolean;
  onSelect: (id: string) => void;
  id: string;
}

function WorkflowNodeComponent({ data, selected }: { data: WorkflowNodeData; selected?: boolean }) {
  const colors = NODE_COLORS[data.type] || NODE_COLORS.message;
  const isEndOrTransfer = data.type === 'end' || data.type === 'transfer';

  return (
    <div
      className={`
        relative rounded-xl border-2 shadow-sm min-w-[160px] max-w-[220px]
        cursor-pointer transition-all
        ${colors.bg} ${colors.border}
        ${selected ? 'ring-2 ring-offset-1 ring-blue-400 shadow-md' : 'hover:shadow-md'}
        ${data.isStart ? 'border-4' : ''}
      `}
      onClick={() => data.onSelect(data.id)}
    >
      {/* Input handle (all nodes except start) */}
      {!data.isStart && (
        <Handle
          type="target"
          position={Position.Top}
          className="!w-3 !h-3 !bg-gray-400 !border-2 !border-white"
        />
      )}

      {/* Header */}
      <div className={`px-3 py-1.5 flex items-center gap-2 rounded-t-xl border-b ${colors.border} bg-white/60`}>
        <span className="text-sm">{NODE_ICONS[data.type]}</span>
        <span className={`text-[11px] font-bold uppercase tracking-wide ${colors.text}`}>
          {NODE_LABELS[data.type]}
        </span>
        {data.isStart && (
          <span className="ml-auto text-[9px] bg-blue-500 text-white px-1.5 py-0.5 rounded-full font-bold">
            INICIO
          </span>
        )}
        {data.hasError && (
          <AlertTriangle size={12} className="ml-auto text-red-500" />
        )}
      </div>

      {/* Body */}
      <div className="px-3 py-2">
        <p className="text-xs font-semibold text-gray-700 truncate">{data.label}</p>
        {data.content && (
          <p className="text-[10px] text-gray-500 mt-0.5 line-clamp-2 leading-tight">
            {data.content}
          </p>
        )}
        {data.variable && (
          <span className="inline-block mt-1 text-[9px] bg-purple-100 text-purple-700 px-1.5 py-0.5 rounded font-mono">
            → {data.variable}
          </span>
        )}
        {data.type === 'schedule' && data.delay_days != null && (
          <span className="inline-block mt-1 text-[9px] bg-teal-100 text-teal-700 px-1.5 py-0.5 rounded">
            +{data.delay_days}d
          </span>
        )}
      </div>

      {/* Output handle (all except end) */}
      {!isEndOrTransfer && (
        <Handle
          type="source"
          position={Position.Bottom}
          className="!w-3 !h-3 !bg-blue-400 !border-2 !border-white"
        />
      )}
    </div>
  );
}

const nodeTypes: NodeTypes = {
  workflowNode: WorkflowNodeComponent,
};

// ── Node panel (editor lateral) ───────────────────────────────────────────────
interface NodePanelProps {
  node: WorkflowNode | null;
  isStart: boolean;
  mode: 'workflow' | 'mixed';
  edges: WorkflowEdge[];
  allNodes: WorkflowNode[];
  onUpdate: (updated: WorkflowNode) => void;
  onDelete: () => void;
  onSetStart: () => void;
  onAddEdge: (edge: Omit<WorkflowEdge, 'id'>) => void;
  onDeleteEdge: (edgeId: string) => void;
  onClose: () => void;
}

function NodePanel({
  node, isStart, mode, edges, allNodes,
  onUpdate, onDelete, onSetStart, onAddEdge, onDeleteEdge, onClose,
}: NodePanelProps) {
  if (!node) return null;
  const outEdges = edges.filter(e => e.source === node.id);

  return (
    <div className="absolute top-0 right-0 h-full w-72 bg-white border-l border-gray-200 shadow-xl z-10 flex flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 bg-gray-50 border-b border-gray-200">
        <div className="flex items-center gap-2">
          <span>{NODE_ICONS[node.type]}</span>
          <span className="font-bold text-sm text-gray-800">{NODE_LABELS[node.type]}</span>
        </div>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
          <X size={16} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Label */}
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Etiqueta</label>
          <input
            type="text"
            value={node.label}
            onChange={e => onUpdate({ ...node, label: e.target.value })}
            className="w-full px-3 py-1.5 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500/20 outline-none"
          />
        </div>

        {/* Content (message, question) */}
        {(node.type === 'message' || node.type === 'question') && (
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              {node.type === 'message' ? 'Texto exacto que dirá el agente' : 'Texto de la pregunta'}
            </label>
            <textarea
              rows={4}
              value={node.content || ''}
              onChange={e => onUpdate({ ...node, content: e.target.value })}
              className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500/20 outline-none resize-none"
              placeholder={node.type === 'message' ? 'Hola, le llamo de...' : '¿Con quién tengo el gusto?'}
            />
          </div>
        )}

        {/* Variable (question) */}
        {node.type === 'question' && (
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              Guardar respuesta en variable
            </label>
            <input
              type="text"
              value={node.variable || ''}
              onChange={e => onUpdate({ ...node, variable: e.target.value })}
              placeholder="nombre_cliente"
              className="w-full px-3 py-1.5 border border-gray-200 rounded-lg text-sm font-mono focus:ring-2 focus:ring-purple-500/20 outline-none"
            />
          </div>
        )}

        {/* Options (question) */}
        {node.type === 'question' && (
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              Opciones de respuesta (opcional)
            </label>
            <input
              type="text"
              value={(node.options || []).join(', ')}
              onChange={e => onUpdate({ ...node, options: e.target.value.split(',').map(s => s.trim()).filter(Boolean) })}
              placeholder="sí, no, no sé"
              className="w-full px-3 py-1.5 border border-gray-200 rounded-lg text-xs focus:ring-2 focus:ring-purple-500/20 outline-none"
            />
            <p className="text-[10px] text-gray-400 mt-0.5">Separadas por coma</p>
          </div>
        )}

        {node.type === 'llm_free' && mode === 'mixed' && (
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              Sub-prompt de este nodo
            </label>
            <textarea
              rows={5}
              value={node.prompt || ''}
              onChange={e => onUpdate({ ...node, prompt: e.target.value })}
              placeholder="El agente puede responder libremente sobre..."
              className="w-full px-3 py-2 border border-emerald-200 bg-emerald-50/30 rounded-lg text-sm focus:ring-2 focus:ring-emerald-500/20 outline-none resize-none"
            />
          </div>
        )}

        {node.type === 'schedule' && (
          <>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Días hasta el seguimiento</label>
              <input
                type="number"
                min={1}
                max={365}
                value={node.delay_days ?? 3}
                onChange={e => onUpdate({ ...node, delay_days: Math.max(1, Number(e.target.value) || 1) })}
                className="w-full px-3 py-1.5 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-teal-500/20 outline-none"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Referencia de campaña</label>
              <input
                type="text"
                value={node.campaign_id_ref ?? '{{campaign_id}}'}
                onChange={e => onUpdate({ ...node, campaign_id_ref: e.target.value })}
                placeholder="{{campaign_id}}"
                className="w-full px-3 py-1.5 border border-gray-200 rounded-lg text-sm font-mono focus:ring-2 focus:ring-teal-500/20 outline-none"
              />
              <p className="text-[10px] text-gray-400 mt-0.5">Usa {'{{campaign_id}}'} o el ID numérico</p>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Mensaje opcional al cliente</label>
              <textarea
                rows={2}
                value={node.content || ''}
                onChange={e => onUpdate({ ...node, content: e.target.value })}
                placeholder="Le llamaremos en unos días para hacer seguimiento."
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-teal-500/20 outline-none resize-none"
              />
            </div>
          </>
        )}

        {/* Edges / transitions */}
        {node.type !== 'end' && node.type !== 'transfer' && (
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              Transiciones de salida
            </label>
            <div className="space-y-2">
              {outEdges.map(e => {
                const targetNode = allNodes.find(n => n.id === e.target);
                return (
                  <div key={e.id} className="flex items-center gap-2 bg-gray-50 rounded-lg p-2">
                    <div className="flex-1 min-w-0">
                      <p className="text-[10px] text-gray-500 truncate">
                        {e.condition && e.condition !== 'default'
                          ? `Si: ${e.condition}`
                          : 'Por defecto'}
                      </p>
                      <p className="text-xs font-medium text-gray-700 truncate">
                        → {targetNode?.label || e.target}
                      </p>
                    </div>
                    <button
                      onClick={() => onDeleteEdge(e.id)}
                      className="text-gray-400 hover:text-red-500 flex-shrink-0"
                    >
                      <X size={12} />
                    </button>
                  </div>
                );
              })}
              <div className="text-[10px] text-gray-400 italic">
                Arrastra desde el handle inferior de este nodo hacia otro nodo para añadir transiciones.
              </div>
            </div>
          </div>
        )}

        {/* Actions */}
        <div className="space-y-2 pt-2 border-t border-gray-100">
          {!isStart && (
            <button
              onClick={onSetStart}
              className="w-full text-xs py-1.5 bg-blue-50 text-blue-700 border border-blue-200 rounded-lg hover:bg-blue-100 transition-colors"
            >
              ⭐ Establecer como nodo inicial
            </button>
          )}
          <button
            onClick={onDelete}
            className="w-full text-xs py-1.5 bg-red-50 text-red-600 border border-red-200 rounded-lg hover:bg-red-100 transition-colors"
          >
            🗑️ Eliminar nodo
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Conversión WorkflowDefinition ↔ React Flow nodes/edges ───────────────────

function wfNodesToRFNodes(
  nodes: WorkflowNode[],
  startNode: string,
  selectedId: string | null,
  errorIds: Set<string>,
  onSelect: (id: string) => void,
): Node[] {
  return nodes.map((n, idx) => ({
    id: n.id,
    type: 'workflowNode',
    position: n.position || { x: 150 * (idx % 4), y: 150 * Math.floor(idx / 4) },
    data: {
      id: n.id,
      label: n.label || NODE_LABELS[n.type],
      type: n.type,
      content: n.content,
      prompt: n.prompt,
      variable: n.variable,
      delay_days: n.delay_days,
      isStart: n.id === startNode,
      hasError: errorIds.has(n.id),
      onSelect,
    } as WorkflowNodeData,
    selected: n.id === selectedId,
  }));
}

function wfEdgesToRFEdges(edges: WorkflowEdge[]): Edge[] {
  return edges.map(e => ({
    id: e.id,
    source: e.source,
    target: e.target,
    label: e.condition && e.condition !== 'default' ? e.condition : undefined,
    style: { stroke: '#94a3b8' },
    labelStyle: { fontSize: 10 },
    animated: false,
  }));
}

// ── Validation ─────────────────────────────────────────────────────────────────

function validateWorkflow(def: WorkflowDefinition): { errors: string[]; errorNodeIds: Set<string> } {
  const errors: string[] = [];
  const errorNodeIds = new Set<string>();
  const { nodes, edges, start_node } = def;

  if (!start_node || !nodes.find(n => n.id === start_node)) {
    errors.push('No hay nodo inicial definido.');
  }

  const endNodes = nodes.filter(n => n.type === 'end');
  if (endNodes.length === 0) {
    errors.push('Debe existir al menos un nodo de tipo "Fin".');
  }

  const edgeSources = new Set(edges.map(e => e.source));
  for (const n of nodes) {
    if (n.type !== 'end' && n.type !== 'transfer' && !edgeSources.has(n.id)) {
      errors.push(`El nodo "${n.label || n.id}" no tiene edge de salida.`);
      errorNodeIds.add(n.id);
    }
  }

  return { errors, errorNodeIds };
}

// ── ID generator ──────────────────────────────────────────────────────────────
let _idCounter = 1;
function genId(prefix: string) {
  return `${prefix}_${Date.now()}_${_idCounter++}`;
}

// ── WorkflowEditor component ──────────────────────────────────────────────────

interface WorkflowEditorProps {
  value: WorkflowDefinition | null;
  onChange: (wf: WorkflowDefinition) => void;
  mode: 'workflow' | 'mixed';
}

const EMPTY_WF: WorkflowDefinition = { nodes: [], edges: [], start_node: '' };

export default function WorkflowEditor({ value, onChange, mode }: WorkflowEditorProps) {
  const wf = value || EMPTY_WF;
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  const { errors, errorNodeIds } = useMemo(() => validateWorkflow(wf), [wf]);

  // RF state
  const rfNodes = useMemo(
    () => wfNodesToRFNodes(wf.nodes, wf.start_node, selectedNodeId, errorNodeIds, setSelectedNodeId),
    [wf.nodes, wf.start_node, selectedNodeId, errorNodeIds]
  );
  const rfEdges = useMemo(() => wfEdgesToRFEdges(wf.edges), [wf.edges]);

  const [nodes, setNodes, onNodesChange] = useNodesState(rfNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(rfEdges);

  // Sync RF → value (posiciones y movimientos)
  useEffect(() => {
    setNodes(wfNodesToRFNodes(wf.nodes, wf.start_node, selectedNodeId, errorNodeIds, setSelectedNodeId));
  }, [wf, selectedNodeId, errorNodeIds]);

  useEffect(() => {
    setEdges(wfEdgesToRFEdges(wf.edges));
  }, [wf.edges]);

  // Persist position changes back to wf
  const handleNodesChange = useCallback(
    (changes: any[]) => {
      onNodesChange(changes);
      // Update positions in wf
      const posChanges = changes.filter((c: any) => c.type === 'position' && c.position);
      if (posChanges.length > 0) {
        const posMap: Record<string, { x: number; y: number }> = {};
        posChanges.forEach((c: any) => { posMap[c.id] = c.position; });
        onChange({
          ...wf,
          nodes: wf.nodes.map(n => posMap[n.id] ? { ...n, position: posMap[n.id] } : n),
        });
      }
    },
    [wf, onChange, onNodesChange]
  );

  // New edge from drag
  const onConnect = useCallback(
    (connection: Connection) => {
      const newEdge: WorkflowEdge = {
        id: genId('edge'),
        source: connection.source || '',
        target: connection.target || '',
        condition: null,
      };
      onChange({ ...wf, edges: [...wf.edges, newEdge] });
    },
    [wf, onChange]
  );

  // Add new node
  const addNode = (type: WorkflowNodeType) => {
    const id = genId('node');
    const newNode: WorkflowNode = {
      id,
      type,
      label: NODE_LABELS[type],
      position: { x: 200 + Math.random() * 100, y: 100 + wf.nodes.length * 120 },
      ...(type === 'schedule'
        ? { delay_days: 3, campaign_id_ref: '{{campaign_id}}' }
        : {}),
    };
    const updatedNodes = [...wf.nodes, newNode];
    onChange({
      ...wf,
      nodes: updatedNodes,
      start_node: wf.start_node || id,
    });
    setSelectedNodeId(id);
  };

  // Update selected node
  const updateSelectedNode = (updated: WorkflowNode) => {
    onChange({ ...wf, nodes: wf.nodes.map(n => n.id === updated.id ? updated : n) });
  };

  // Delete selected node
  const deleteSelectedNode = () => {
    if (!selectedNodeId) return;
    const newNodes = wf.nodes.filter(n => n.id !== selectedNodeId);
    const newEdges = wf.edges.filter(e => e.source !== selectedNodeId && e.target !== selectedNodeId);
    const newStart = wf.start_node === selectedNodeId ? (newNodes[0]?.id || '') : wf.start_node;
    onChange({ ...wf, nodes: newNodes, edges: newEdges, start_node: newStart });
    setSelectedNodeId(null);
  };

  const deleteEdge = (edgeId: string) => {
    onChange({ ...wf, edges: wf.edges.filter(e => e.id !== edgeId) });
  };

  const setAsStart = () => {
    if (selectedNodeId) onChange({ ...wf, start_node: selectedNodeId });
  };

  const selectedNode = wf.nodes.find(n => n.id === selectedNodeId) || null;

  const NODE_TYPES_TO_ADD: { type: WorkflowNodeType; label: string; hidden?: boolean }[] = [
    { type: 'message',   label: '💬 Mensaje' },
    { type: 'question',  label: '❓ Pregunta' },
    { type: 'condition', label: '🔀 Condición' },
    { type: 'llm_free',  label: '🤖 LLM libre', hidden: mode !== 'mixed' },
    { type: 'schedule',  label: '📅 Programar seguimiento' },
    { type: 'transfer',  label: '📞 Transferir' },
    { type: 'end',       label: '🏁 Fin' },
  ];

  return (
    <div className="relative w-full h-full bg-gray-50 flex flex-col">
      {/* Toolbar */}
      <div className="flex items-center gap-1.5 px-3 py-2 bg-white border-b border-gray-200 flex-wrap">
        <span className="text-xs text-gray-500 font-medium mr-1">+ Añadir:</span>
        {NODE_TYPES_TO_ADD.filter(n => !n.hidden).map(({ type, label }) => (
          <button
            key={type}
            onClick={() => addNode(type)}
            className="text-[11px] px-2.5 py-1 rounded-lg border border-gray-200 bg-white hover:bg-gray-50 text-gray-700 transition-colors"
          >
            {label}
          </button>
        ))}
        {/* Validation indicator */}
        <div className="ml-auto flex items-center gap-1.5">
          {errors.length === 0 ? (
            <span className="flex items-center gap-1 text-[11px] text-emerald-600">
              <CheckCircle size={12} /> Válido
            </span>
          ) : (
            <span className="flex items-center gap-1 text-[11px] text-amber-600">
              <AlertTriangle size={12} /> {errors.length} error(es)
            </span>
          )}
        </div>
      </div>

      {/* Validation errors */}
      {errors.length > 0 && (
        <div className="bg-amber-50 border-b border-amber-200 px-4 py-2">
          {errors.map((e, i) => (
            <p key={i} className="text-[11px] text-amber-700">⚠️ {e}</p>
          ))}
        </div>
      )}

      {/* Canvas */}
      <div className="flex-1 relative">
        {wf.nodes.length === 0 ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-gray-400 select-none">
            <GitBranchIcon />
            <p className="text-sm font-medium mt-3">Empieza añadiendo un nodo</p>
            <p className="text-xs mt-1">Usa los botones de arriba para añadir el primer nodo</p>
          </div>
        ) : (
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={handleNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            nodeTypes={nodeTypes}
            fitView
            fitViewOptions={{ padding: 0.3 }}
            deleteKeyCode={null}
          >
            <Background color="#e2e8f0" gap={16} />
            <Controls />
            <MiniMap nodeStrokeWidth={3} pannable zoomable />
          </ReactFlow>
        )}

        {/* Node editor panel */}
        {selectedNode && (
          <NodePanel
            node={selectedNode}
            isStart={wf.start_node === selectedNode.id}
            mode={mode}
            edges={wf.edges}
            allNodes={wf.nodes}
            onUpdate={updateSelectedNode}
            onDelete={deleteSelectedNode}
            onSetStart={setAsStart}
            onAddEdge={e => onChange({ ...wf, edges: [...wf.edges, { ...e, id: genId('edge') }] })}
            onDeleteEdge={deleteEdge}
            onClose={() => setSelectedNodeId(null)}
          />
        )}
      </div>
    </div>
  );
}

// Small inline icon to avoid extra imports
function GitBranchIcon() {
  return (
    <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <line x1="6" y1="3" x2="6" y2="15" />
      <circle cx="18" cy="6" r="3" />
      <circle cx="6" cy="18" r="3" />
      <path d="M18 9a9 9 0 0 1-9 9" />
    </svg>
  );
}
