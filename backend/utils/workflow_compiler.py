"""
workflow_compiler.py
--------------------
Compila un workflow_definition (grafo JSON) en:
  1. Un system-prompt estructurado que el LLM puede seguir paso a paso.
  2. Una lista de pasos normalizados para WorkflowStateMachine.

La compilación ocurre UNA SOLA VEZ al arrancar la sesión (en DynamicAgent.__init__),
no en cada turno, porque es costosa y el grafo no cambia durante la llamada.
"""

from __future__ import annotations

import logging

from utils.prompt_sanitizer import sanitize_untrusted_text
import uuid
from typing import Any

logger = logging.getLogger("agent-dynamic")

# ── Tipos de nodo soportados ────────────────────────────────────────────────
NODE_TYPES = frozenset({
    "message",    # El agente dice texto fijo y avanza
    "question",   # El agente pregunta, espera respuesta, guarda variable
    "condition",  # Routing puro: no habla, evalúa variables
    "llm_free",   # Nodo libre: el LLM improvisa con su sub-prompt (modo mixed)
    "schedule",   # Programa llamada de seguimiento en N días
    "transfer",   # Llama a transferir_a_agente_humano
    "end",        # Llama a guardar_encuesta + finalizar_llamada
})


def _resolve_node_map(nodes: list[dict]) -> dict[str, dict]:
    """Devuelve {node_id: node_dict} para acceso O(1)."""
    return {n["id"]: n for n in nodes if isinstance(n, dict) and n.get("id")}


def _build_adjacency(edges: list[dict]) -> dict[str, list[dict]]:
    """
    Devuelve {source_id: [edge, ...]} ordenando los edges para que
    "default" siempre quede al final (se evalúa si ninguna condición acierta).
    """
    adj: dict[str, list[dict]] = {}
    for e in edges:
        if not isinstance(e, dict):
            continue
        src = e.get("source")
        if not src:
            continue
        adj.setdefault(src, []).append(e)

    # Ordenar: condiciones explícitas primero, "default"/None al final
    for src in adj:
        adj[src].sort(key=lambda e: (
            0 if (e.get("condition") and e["condition"] != "default") else 1
        ))

    return adj


def _topological_order(
    start_node: str,
    node_map: dict[str, dict],
    adj: dict[str, list[dict]],
) -> list[str]:
    """
    BFS desde start_node para obtener orden de visita de los nodos.
    Detecta ciclos incluyendo cada nodo solo una vez.
    """
    visited: list[str] = []
    seen: set[str] = set()
    queue = [start_node]

    while queue:
        nid = queue.pop(0)
        if nid in seen or nid not in node_map:
            continue
        seen.add(nid)
        visited.append(nid)
        for edge in adj.get(nid, []):
            target = edge.get("target")
            if target and target not in seen:
                queue.append(target)

    return visited


def _step_number_map(ordered_ids: list[str]) -> dict[str, int]:
    """Devuelve {node_id: número_de_paso_1-indexed}."""
    return {nid: i + 1 for i, nid in enumerate(ordered_ids)}


def _format_prompt_block(
    step_num: int,
    node: dict,
    adj: dict[str, list[dict]],
    step_nums: dict[str, int],
    mode: str,
) -> str:
    """Formatea un bloque de texto para el nodo dado."""
    ntype = node.get("type", "message")
    label = node.get("label") or f"Paso {step_num}"

    lines: list[str] = []

    if ntype == "message":
        content = sanitize_untrusted_text(
            (node.get("content") or "").strip(),
            max_length=2000,
            field_name="workflow_message",
        )
        lines.append(f"PASO {step_num} [{label}]: Di EXACTAMENTE: \"{content}\"")
        _append_transitions(lines, node, adj, step_nums, default_label="  → Continúa al siguiente paso")

    elif ntype == "question":
        content = sanitize_untrusted_text(
            (node.get("content") or node.get("prompt") or "").strip(),
            max_length=2000,
            field_name="workflow_question",
        )
        variable = node.get("variable") or ""
        options = node.get("options") or []
        lines.append(f"PASO {step_num} [{label}]: Pregunta: \"{content}\"")
        if variable:
            lines.append(f"  → Guarda la respuesta del cliente en la variable '{variable}'")
        if options:
            lines.append(f"  → Opciones esperadas: {', '.join(repr(o) for o in options)}")
        _append_transitions(lines, node, adj, step_nums, default_label="  → Por defecto continúa al siguiente paso")

    elif ntype == "condition":
        lines.append(f"PASO {step_num} [{label}]: (Nodo de decisión — no hables, solo evalúa y avanza)")
        _append_transitions(lines, node, adj, step_nums, default_label="  → Por defecto continúa al siguiente paso")

    elif ntype == "llm_free":
        if mode == "mixed":
            sub_prompt = sanitize_untrusted_text(
                (node.get("prompt") or "").strip(),
                max_length=2000,
                field_name="workflow_sub_prompt",
            )
            lines.append(
                f"PASO {step_num} [{label}]: Nodo libre. Usa el siguiente sub-prompt para este paso:\n"
                f"  \"\"\"\n  {sub_prompt}\n  \"\"\""
            )
        else:
            content = sanitize_untrusted_text(
                (node.get("content") or node.get("prompt") or "").strip(),
                max_length=2000,
                field_name="workflow_llm_free",
            )
            lines.append(f"PASO {step_num} [{label}]: Responde libremente basándote en: \"{content}\"")
        lines.append("  → Cuando termines este segmento, avanza al siguiente paso.")
        _append_transitions(lines, node, adj, step_nums, default_label="  → Por defecto continúa al siguiente paso")

    elif ntype == "transfer":
        lines.append(
            f"PASO {step_num} [{label}]: Transfiere la llamada. "
            "Primero di: \"Entendido, le paso con un compañero. Un momento por favor.\" "
            "Luego llama a la herramienta transferir_a_agente_humano."
        )

    elif ntype == "schedule":
        delay_days = int(node.get("delay_days") or 1)
        campaign_ref = (node.get("campaign_id_ref") or "{{campaign_id}}").strip()
        lines.append(
            f"PASO {step_num} [{label}]: Programa una llamada de seguimiento en {delay_days} día(s) "
            f"(campaña ref: {campaign_ref})."
        )
        lines.append(
            "  → El sistema registrará el seguimiento automáticamente; no cuelgues por este motivo."
        )
        _append_transitions(lines, node, adj, step_nums, default_label="  → Continúa al siguiente paso")

    elif ntype == "end":
        lines.append(
            f"PASO {step_num} [{label}]: Fin del guion. "
            "Despídete brevemente, llama a la herramienta guardar_encuesta "
            "y luego a finalizar_llamada."
        )

    else:
        fallback = sanitize_untrusted_text(
            node.get("content", ""),
            max_length=2000,
            field_name="workflow_node",
        )
        lines.append(f"PASO {step_num} [{label}]: {fallback}")

    return "\n".join(lines)


def _append_transitions(
    lines: list[str],
    node: dict,
    adj: dict[str, list[dict]],
    step_nums: dict[str, int],
    default_label: str,
) -> None:
    """Añade las reglas de transición al bloque de texto del nodo."""
    node_edges = adj.get(node["id"], [])
    explicit = [e for e in node_edges if e.get("condition") and e["condition"] != "default"]
    default_edges = [e for e in node_edges if not e.get("condition") or e["condition"] == "default"]

    for edge in explicit:
        target_step = step_nums.get(edge.get("target", ""), "?")
        lines.append(f"  → Si {edge['condition']} → ve al PASO {target_step}")

    if default_edges:
        target_step = step_nums.get(default_edges[0].get("target", ""), "?")
        lines.append(f"  → Por defecto → ve al PASO {target_step}")
    else:
        lines.append(default_label)


def _normalize_steps(
    ordered_ids: list[str],
    node_map: dict[str, dict],
    adj: dict[str, list[dict]],
) -> list[dict]:
    """
    Genera la lista de pasos normalizados para WorkflowStateMachine.
    Cada paso tiene la forma:
      {
        "id": str,
        "type": str,
        "content": str,
        "prompt": str | None,
        "variable": str | None,
        "next_default": str | None,   # node_id del siguiente por defecto
        "conditions": [{"expr": str, "target": str}]
      }
    """
    steps: list[dict] = []
    for nid in ordered_ids:
        node = node_map[nid]
        edges = adj.get(nid, [])

        conditions = [
            {"expr": e["condition"], "target": e["target"]}
            for e in edges
            if e.get("condition") and e["condition"] != "default" and e.get("target")
        ]
        default_targets = [
            e["target"] for e in edges
            if (not e.get("condition") or e["condition"] == "default") and e.get("target")
        ]
        next_default = default_targets[0] if default_targets else None

        steps.append({
            "id": nid,
            "type": node.get("type", "message"),
            "label": node.get("label") or nid,
            "content": (node.get("content") or "").strip(),
            "prompt": (node.get("prompt") or None),
            "variable": (node.get("variable") or None),
            "options": node.get("options") or [],
            "delay_days": node.get("delay_days"),
            "campaign_id_ref": node.get("campaign_id_ref"),
            "next_default": next_default,
            "conditions": conditions,
        })
    return steps


# ── Public API ───────────────────────────────────────────────────────────────

def compile_workflow_to_prompt(
    workflow_definition: dict,
    agent_mode: str,
    base_instructions: str,
) -> tuple[str, list[dict]]:
    """
    Compila un workflow_definition en:
      - Un system prompt que describe el guion paso a paso para el LLM.
      - Una lista de pasos normalizados para WorkflowStateMachine.

    Args:
        workflow_definition: El JSONB del campo workflow_definition de agent_config.
        agent_mode: "workflow" o "mixed".
        base_instructions: El campo instructions del agente (se añade como contexto global).

    Returns:
        (compiled_prompt: str, steps: list[dict])
    """
    if not workflow_definition or not isinstance(workflow_definition, dict):
        logger.warning("compile_workflow_to_prompt: workflow_definition vacío o inválido")
        return base_instructions, []

    nodes: list[dict] = workflow_definition.get("nodes") or []
    edges: list[dict] = workflow_definition.get("edges") or []
    start_node: str = workflow_definition.get("start_node") or ""

    if not nodes:
        logger.warning("compile_workflow_to_prompt: sin nodos en el workflow")
        return base_instructions, []

    node_map = _resolve_node_map(nodes)

    # Fallback: si no hay start_node explícito, usar el primero
    if not start_node or start_node not in node_map:
        start_node = nodes[0].get("id", "")
        logger.info(f"compile_workflow_to_prompt: start_node no definido, usando '{start_node}'")

    adj = _build_adjacency(edges)
    ordered_ids = _topological_order(start_node, node_map, adj)
    step_nums = _step_number_map(ordered_ids)

    # Construir bloques del prompt
    prompt_blocks: list[str] = []
    for nid in ordered_ids:
        node = node_map[nid]
        block = _format_prompt_block(step_nums[nid], node, adj, step_nums, agent_mode)
        prompt_blocks.append(block)

    # Encabezado del prompt compilado
    header_lines = [
        "Sigue este guion PASO A PASO. No improvises el orden ni te saltes pasos.",
        "Espera la respuesta del cliente antes de avanzar cuando el paso lo requiera.",
        "",
    ]
    if mode_is_mixed := (agent_mode == "mixed"):
        header_lines.append(
            "En los pasos de tipo 'Nodo libre' puedes responder con naturalidad "
            "siguiendo el sub-prompt indicado, pero al terminar debes avanzar al siguiente paso."
        )
        header_lines.append("")

    compiled_prompt_parts = header_lines + prompt_blocks

    # Si hay instrucciones base, añadirlas como contexto previo
    if base_instructions and base_instructions.strip():
        preamble = (
            "CONTEXTO Y PERSONALIDAD DEL AGENTE:\n"
            + base_instructions.strip()
            + "\n\n"
            + "━" * 60
            + "\n"
            + "GUION ESTRUCTURADO (sigue este orden estrictamente):\n"
        )
        compiled_prompt = preamble + "\n".join(compiled_prompt_parts)
    else:
        compiled_prompt = "\n".join(compiled_prompt_parts)

    steps = _normalize_steps(ordered_ids, node_map, adj)

    logger.info(
        f"✅ compile_workflow_to_prompt: {len(steps)} pasos compilados "
        f"(modo={agent_mode}, start='{start_node}')"
    )

    return compiled_prompt, steps
