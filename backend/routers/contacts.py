"""
contacts.py — Ficha de Cliente Enriquecida.

Endpoints:
  GET    /api/contacts/             lista paginada con filtros
  GET    /api/contacts/{id}         detalle del contacto
  GET    /api/contacts/{id}/calls   historial de llamadas
  PUT    /api/contacts/{id}         actualiza datos editables
  DELETE /api/contacts/{id}         elimina contacto
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from services.supabase_service import supabase, sb_query
from services.auth import CurrentUser, require_admin, get_current_user

logger = logging.getLogger("api-backend")

router = APIRouter(prefix="/api/contacts", tags=["contacts"])


def _resolve_empresa(user: CurrentUser, empresa_id_param: int | None) -> int:
    if user.role in ("superadmin",) and empresa_id_param:
        return empresa_id_param
    return int(user.empresa_id or 0)


# ─────────────────────────────────────────────────────────────────────────────
# LISTA PAGINADA
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/")
async def list_contacts(
    empresa_id: int | None = Query(None),
    q: str | None = Query(None, description="Búsqueda por nombre o teléfono"),
    disposicion: str | None = Query(None),
    etiqueta: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Lista contactos con filtros y búsqueda debounce-friendly."""
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión a la base de datos")

    eid = _resolve_empresa(current_user, empresa_id)
    if not eid:
        raise HTTPException(status_code=400, detail="empresa_id requerido")

    offset = (page - 1) * page_size

    qb = (
        supabase.table("contactos")
        .select(
            "id, nombre, telefono, email, empresa_nombre, etiquetas, "
            "total_llamadas, ultima_llamada, ultima_disposicion, score, created_at"
        )
        .eq("empresa_id", eid)
    )

    if q:
        # Búsqueda por nombre o teléfono (ilike)
        qb = qb.or_(f"nombre.ilike.%{q}%,telefono.ilike.%{q}%")
    if disposicion:
        qb = qb.eq("ultima_disposicion", disposicion)
    if etiqueta:
        qb = qb.contains("etiquetas", [etiqueta])

    res = await sb_query(
        lambda qb=qb, off=offset, lim=page_size: qb.order("ultima_llamada", desc=True)
        .range(off, off + lim - 1)
        .execute()
    )
    return res.data or []


# ─────────────────────────────────────────────────────────────────────────────
# DETALLE
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{contact_id}")
async def get_contact(
    contact_id: str,
    empresa_id: int | None = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
):
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión a la base de datos")

    eid = _resolve_empresa(current_user, empresa_id)

    res = await sb_query(
        lambda cid=contact_id, eid=eid: supabase.table("contactos")
        .select("*")
        .eq("id", cid)
        .eq("empresa_id", eid)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")
    return res.data[0]


# ─────────────────────────────────────────────────────────────────────────────
# HISTORIAL DE LLAMADAS
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{contact_id}/calls")
async def get_contact_calls(
    contact_id: str,
    empresa_id: int | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Historial de encuestas/llamadas asociadas al teléfono del contacto."""
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión a la base de datos")

    eid = _resolve_empresa(current_user, empresa_id)

    # Obtener teléfono del contacto
    contact_res = await sb_query(
        lambda cid=contact_id, eid=eid: supabase.table("contactos")
        .select("telefono")
        .eq("id", cid)
        .eq("empresa_id", eid)
        .limit(1)
        .execute()
    )
    if not contact_res.data:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")

    telefono = contact_res.data[0]["telefono"]
    offset = (page - 1) * page_size

    # Buscar encuestas cuyo datos_extra.telefono coincida
    enc_res = await sb_query(
        lambda eid=eid, t=telefono, off=offset, lim=page_size: supabase.table("encuestas")
        .select(
            "id, status, created_at, transcription, datos_extra, "
            "seconds_used, comentarios, resumen_llamada"
        )
        .eq("empresa_id", eid)
        .contains("datos_extra", {"telefono": t})
        .order("created_at", desc=True)
        .range(off, off + lim - 1)
        .execute()
    )

    calls = []
    for enc in enc_res.data or []:
        datos = enc.get("datos_extra") or {}
        if isinstance(datos, str):
            import json
            try:
                datos = json.loads(datos)
            except Exception:
                datos = {}
        calls.append({
            "id": enc["id"],
            "fecha": enc.get("created_at"),
            "status": enc.get("status"),
            "disposicion": datos.get("disposicion") or enc.get("status"),
            "sentimiento": datos.get("sentimiento_cliente"),
            "resumen": enc.get("resumen_llamada") or datos.get("resumen_narrativo"),
            "duracion_segundos": enc.get("seconds_used"),
            "comentarios": enc.get("comentarios"),
        })

    return calls


# ─────────────────────────────────────────────────────────────────────────────
# ACTUALIZAR CONTACTO
# ─────────────────────────────────────────────────────────────────────────────

@router.put("/{contact_id}")
async def update_contact(
    contact_id: str,
    payload: dict,
    empresa_id: int | None = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
):
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión a la base de datos")

    eid = _resolve_empresa(current_user, empresa_id)

    allowed_fields = {
        "nombre", "email", "empresa_nombre", "notas", "etiquetas", "score", "datos_extra"
    }
    update: dict[str, Any] = {
        k: v for k, v in payload.items() if k in allowed_fields
    }
    if not update:
        raise HTTPException(status_code=400, detail="Nada que actualizar")

    await sb_query(
        lambda cid=contact_id, eid=eid, d=update: supabase.table("contactos")
        .update(d)
        .eq("id", cid)
        .eq("empresa_id", eid)
        .execute()
    )

    res = await sb_query(
        lambda cid=contact_id, eid=eid: supabase.table("contactos")
        .select("*")
        .eq("id", cid)
        .eq("empresa_id", eid)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")
    return res.data[0]


# ─────────────────────────────────────────────────────────────────────────────
# ELIMINAR CONTACTO
# ─────────────────────────────────────────────────────────────────────────────

@router.delete("/{contact_id}", status_code=204)
async def delete_contact(
    contact_id: str,
    empresa_id: int | None = Query(None),
    current_user: CurrentUser = Depends(require_admin),
):
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión a la base de datos")

    eid = _resolve_empresa(current_user, empresa_id)

    await sb_query(
        lambda cid=contact_id, eid=eid: supabase.table("contactos")
        .delete()
        .eq("id", cid)
        .eq("empresa_id", eid)
        .execute()
    )
    return
