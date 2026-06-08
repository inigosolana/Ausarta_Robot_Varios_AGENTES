# AGENTS.md — Ausarta Robot Varios Agentes

## Arquitectura del proyecto
- Backend: FastAPI en `/backend`
- Agente de voz: LiveKit Agents en `backend/agent.py`
- Base de datos: Supabase/PostgreSQL con pgvector
- Caché: Redis
- Multi-tenant por `empresa_id`

## Servicios clave
- `backend/services/embedding_service.py` → `search_knowledge(empresa_id, query, limit, threshold)`
- `backend/services/external_db_service.py` → `query_external_db(empresa_id, query_name, params)`
- `backend/services/supabase_service.py` → cliente Supabase + `sb_query()`
- `backend/services/redis_service.py` → `get_redis()`

## Reglas obligatorias al tocar agent.py
- NUNCA aceptar SQL libre — solo queries predefinidos en `empresa_external_db.queries`
- Siempre `asyncio.wait_for(..., timeout=5)` en llamadas a BD y KB
- Los errores de KB o BD nunca bloquean la llamada — devolver `""` o `[]` y continuar
- Validar `empresa_id` antes de cualquier query (seguridad multi-tenant)
- Las function_tools usan `context: RunContext` como primer parámetro

## Patrón function_tool de LiveKit
from livekit.agents import function_tool, RunContext

@function_tool
async def nombre_herramienta(context: RunContext, param: str) -> str:
    """Descripción que el LLM ve para decidir cuándo invocarla."""
    try:
        result = await asyncio.wait_for(servicio(param), timeout=5)
        return result or ""
    except Exception as e:
        logger.warning(f"Error en herramienta: {e}")
        return ""

## Tareas pendientes (para que Codex las ejecute)
- [ ] Añadir function_tool `consultar_conocimiento` en agent.py
      que llame a search_knowledge() con el empresa_id de la sesión
- [ ] Añadir function_tool `consultar_cliente` en agent.py
      que llame a query_external_db() con lista blanca de queries
- [ ] Crear SQL para Supabase: tabla knowledge_base + pgvector + función RPC search_knowledge_base
