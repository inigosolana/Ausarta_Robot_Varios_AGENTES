"""
workflow_state.py
-----------------
Máquina de estados liviana que controla en qué paso del workflow
se encuentra una llamada en curso.

Vive en memoria durante la duración de la llamada y no tiene
dependencias externas (solo stdlib). Es instanciada una vez
en DynamicAgent.__init__ y referenciada desde CallSession.
"""

from __future__ import annotations

import ast
import logging
import operator
import re
from typing import Any

logger = logging.getLogger("agent-dynamic")

# ── Evaluación segura de condiciones ────────────────────────────────────────
# Solo se permiten comparaciones simples para evitar exec arbitrario.
_SAFE_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}

_ALLOWED_EXPR_PATTERN = re.compile(
    r"^[a-zA-Z_][a-zA-Z0-9_]*"          # variable o literal
    r"\s*(==|!=|<=|>=|<|>|in|not in)\s*"  # operador permitido
    r".+$"                                # valor
)


def _safe_eval_condition(expr: str, variables: dict[str, Any]) -> bool:
    """
    Evalúa una condición simple de forma segura.
    Solo permite: var == val, var != val, var in list, var not in list, etc.
    Si la expresión no es parseable o usa construcciones no permitidas,
    devuelve False para que se use la condición "default".

    Ejemplos válidos:
        respuesta == 'sí'
        nota >= 4
        idioma in ['es', 'eu']
        respuesta != 'no'
    """
    if not expr or not isinstance(expr, str):
        return False

    expr = expr.strip()

    # Comprobación rápida de patrón
    if not _ALLOWED_EXPR_PATTERN.match(expr):
        logger.debug(f"[workflow_state] Condición rechazada (patrón): '{expr}'")
        return False

    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        logger.debug(f"[workflow_state] Condición rechazada (SyntaxError): '{expr}'")
        return False

    body = tree.body

    # Solo aceptamos comparaciones binarias
    if not isinstance(body, ast.Compare):
        logger.debug(f"[workflow_state] Condición rechazada (no es Compare): '{expr}'")
        return False

    if len(body.ops) != 1 or len(body.comparators) != 1:
        return False

    op_type = type(body.ops[0])
    if op_type not in _SAFE_OPS:
        logger.debug(f"[workflow_state] Operador no permitido: {op_type.__name__}")
        return False

    try:
        # Resolvemos el lado izquierdo (debe ser un nombre de variable o literal)
        left_node = body.left
        if isinstance(left_node, ast.Name):
            left = variables.get(left_node.id)
        else:
            left = ast.literal_eval(left_node)  # type: ignore[arg-type]

        right = ast.literal_eval(body.comparators[0])  # type: ignore[arg-type]
    except (ValueError, TypeError) as exc:
        logger.debug(f"[workflow_state] No se pudo resolver valores de '{expr}': {exc}")
        return False

    # FIX E — comparaciones string case-insensitive.
    if isinstance(left, str) and isinstance(right, str):
        left = left.strip().lower()
        right = right.strip().lower()

    try:
        result = _SAFE_OPS[op_type](left, right)
        return bool(result)
    except TypeError:
        return False


# ── WorkflowStateMachine ─────────────────────────────────────────────────────

class WorkflowStateMachine:
    """
    Máquina de estados para workflows de agente de voz.

    Parámetros
    ----------
    steps : list[dict]
        Lista de pasos normalizados generados por compile_workflow_to_prompt().
        Cada paso tiene: id, type, content, prompt, variable, next_default,
        conditions ([{expr, target}]).
    variables : dict
        Variables iniciales (generalmente el campo workflow_variables de agent_config,
        con valores a null). Se rellenan durante la llamada.
    """

    def __init__(self, steps: list[dict], variables: dict | None = None) -> None:
        self._steps: list[dict] = steps
        self._step_index: dict[str, dict] = {s["id"]: s for s in steps}
        self._variables: dict[str, Any] = dict(variables or {})
        self._current_id: str | None = steps[0]["id"] if steps else None
        self._finished: bool = False

        logger.info(
            f"[workflow_state] Máquina iniciada: {len(steps)} pasos, "
            f"inicio='{self._current_id}'"
        )

    # ── Consultas de estado ──────────────────────────────────────────────────

    def current_step(self) -> dict | None:
        """Devuelve el nodo activo o None si terminó."""
        if self._finished or not self._current_id:
            return None
        return self._step_index.get(self._current_id)

    def is_finished(self) -> bool:
        """True si el workflow llegó a un nodo tipo 'end' o se agotaron pasos."""
        return self._finished

    def get_variables(self) -> dict[str, Any]:
        """Devuelve todas las variables acumuladas hasta ahora."""
        return dict(self._variables)

    # ── Mutaciones de estado ─────────────────────────────────────────────────

    def set_variable(self, name: str, value: Any) -> None:
        """Guarda una variable capturada durante la llamada."""
        old = self._variables.get(name)
        self._variables[name] = value
        logger.info(
            f"[workflow_state] Variable '{name}': {old!r} → {value!r}"
        )

    def advance(self, user_response: str = "") -> dict | None:
        """
        Evalúa las condiciones del nodo actual usando user_response y las
        variables acumuladas, avanza al siguiente nodo y lo devuelve.
        Devuelve None si no hay siguiente nodo (fin del workflow).

        La evaluación sigue este orden:
        1. Condiciones explícitas (en orden de definición, primera que cumple gana).
        2. Edge "default" o next_default.
        3. Si no hay ningún edge, el workflow termina.
        """
        if self._finished or not self._current_id:
            logger.debug("[workflow_state] advance() llamado en estado terminado")
            return None

        current = self._step_index.get(self._current_id)
        if not current:
            logger.warning(f"[workflow_state] Nodo actual '{self._current_id}' no encontrado")
            self._finished = True
            return None

        # Nodos finales: marcar como terminado y no avanzar
        if current["type"] in ("end", "transfer"):
            self._finished = True
            logger.info(f"[workflow_state] Workflow finalizado en nodo '{self._current_id}' ({current['type']})")
            return None

        # Contexto para evaluación de condiciones:
        # incluye las variables acumuladas + _response con la última respuesta
        # FIX E — normalizar variables string para evaluación robusta.
        eval_ctx: dict[str, Any] = {
            k: (v.strip().lower() if isinstance(v, str) else v)
            for k, v in self._variables.items()
        }
        if user_response:
            eval_ctx["_response"] = user_response.strip().lower()
            # También intentamos mapear el valor a la variable activa del nodo
            var_name = current.get("variable")
            if var_name and var_name not in eval_ctx:
                eval_ctx[var_name] = user_response.strip().lower()

        # 1. Evaluar condiciones explícitas
        next_id: str | None = None
        for cond in current.get("conditions") or []:
            expr = cond.get("expr") or ""
            target = cond.get("target") or ""
            if not target:
                continue
            if _safe_eval_condition(expr, eval_ctx):
                next_id = target
                logger.info(
                    f"[workflow_state] '{self._current_id}' → '{next_id}' "
                    f"(condición cumplida: '{expr}')"
                )
                break

        # 2. Fallback a default
        if not next_id:
            next_id = current.get("next_default")
            if next_id:
                logger.info(
                    f"[workflow_state] '{self._current_id}' → '{next_id}' (default)"
                )
            else:
                logger.info(
                    f"[workflow_state] '{self._current_id}' sin siguiente nodo — fin del workflow"
                )
                self._finished = True
                return None

        # Mover al siguiente nodo
        self._current_id = next_id
        next_step = self._step_index.get(next_id)

        if not next_step:
            logger.warning(f"[workflow_state] Nodo siguiente '{next_id}' no existe — fin del workflow")
            self._finished = True
            return None

        if next_step["type"] in ("end", "transfer"):
            self._finished = True
            logger.info(f"[workflow_state] Workflow finalizado en nodo '{next_id}' ({next_step['type']})")

        return next_step

    # ── Debug ────────────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"<WorkflowStateMachine current='{self._current_id}' "
            f"finished={self._finished} vars={list(self._variables.keys())}>"
        )
