"""
json_logger.py — Formatter de logging estructurado en JSON.

Incluye automáticamente en cada línea:
  timestamp, level, logger, message,
  empresa_id (del ContextVar si existe), request_id/path si están en el record.

Compatible con el FileHandler existente. No requiere dependencias externas:
usa el módulo `json` estándar en lugar de python-json-logger.

Uso en api.py / agent.py:
    from services.json_logger import configure_json_logging
    configure_json_logging(level=logging.INFO, log_file="api.log")
"""
from __future__ import annotations

import json
import logging
import os
import sys
import traceback
from datetime import datetime, timezone
from typing import Any


class JsonFormatter(logging.Formatter):
    """
    Formatea un LogRecord como una línea JSON compacta.

    Campos emitidos:
      - ts         : ISO 8601 UTC (siempre presente)
      - level      : DEBUG / INFO / WARNING / ERROR / CRITICAL
      - logger     : nombre del logger
      - msg        : mensaje formateado (con args interpolados)
      - empresa_id : del ContextVar si existe (omitido si None)
      - request_id : extra["request_id"] si existe
      - path       : extra["path"] si existe
      - exc        : traceback compacto si hay excepción (una sola línea)
    """

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }

        # empresa_id desde ContextVar (evita importar si no está disponible)
        try:
            from services.tenant_context import get_current_empresa_id
            eid = get_current_empresa_id()
            if eid is not None:
                payload["empresa_id"] = eid
        except Exception:
            pass

        # Campos extra opcionales
        for field in ("request_id", "path", "method", "status_code", "duration_ms"):
            val = getattr(record, field, None)
            if val is not None:
                payload[field] = val

        # Excepción
        if record.exc_info:
            payload["exc"] = "".join(traceback.format_exception(*record.exc_info)).strip()

        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_json_logging(
    level: int = logging.INFO,
    log_file: str | None = None,
    force: bool = False,
) -> None:
    """
    Reemplaza los handlers del root logger con JsonFormatter.

    Args:
        level:    Nivel mínimo de logging (default INFO).
        log_file: Ruta al archivo de log (None → solo stdout).
        force:    Si True, elimina handlers existentes antes de añadir los nuevos.
    """
    root = logging.getLogger()
    if force:
        for h in root.handlers[:]:
            root.removeHandler(h)
            h.close()

    formatter = JsonFormatter()

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)
    root.addHandler(stdout_handler)

    if log_file:
        try:
            file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        except Exception as exc:
            logging.warning("No se pudo abrir log file %s: %s", log_file, exc)

    root.setLevel(level)


class RequestLoggingMiddleware:
    """
    ASGI middleware opcional que añade request_id, path, method y duration_ms
    a cada línea de log emitida durante el request.

    Añadir en api.py ANTES de TenantContextMiddleware si se quiere request_id:
        app.add_middleware(RequestLoggingMiddleware)
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        import uuid
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid.uuid4())[:8]
        path = scope.get("path", "")
        method = scope.get("method", "")

        import time
        start = time.monotonic()

        # Inyectar en el contexto de logging usando un Filter temporal
        class _RequestFilter(logging.Filter):
            def filter(self, record: logging.LogRecord) -> bool:
                record.request_id = request_id
                record.path = path
                record.method = method
                return True

        fltr = _RequestFilter()
        logging.getLogger().addFilter(fltr)
        try:
            await self.app(scope, receive, send)
        finally:
            logging.getLogger().removeFilter(fltr)
