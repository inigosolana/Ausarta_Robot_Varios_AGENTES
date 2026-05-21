import logging
from datetime import datetime, timezone
from typing import Optional

from services.supabase_service import insert_row_async, supabase

logger = logging.getLogger("api-backend")


async def log_audit_event(
    user_id: Optional[str],
    action: str,
    target_type: str,
    target_id: str,
    metadata: Optional[dict] = None,
) -> None:
    """
    Registra evento de auditoría en audit_logs.
    No rompe flujo de negocio si falla (best-effort + warning).
    """
    if not supabase:
        return
    try:
        payload = {
            "user_id": user_id,
            "action": action,
            "target_type": target_type,
            "target_id": str(target_id),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata or {},
        }
        await insert_row_async("audit_logs", payload)
    except Exception as e:
        logger.warning(f"⚠️ [Audit] Error registrando evento {action} {target_type}/{target_id}: {e}")

