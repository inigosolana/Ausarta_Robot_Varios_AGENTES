"""CRUD y sincronización de extensiones Yeastar por empresa."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from services.auth import CurrentUser, get_current_user, require_admin
from services.platform_access import has_global_access
from services.supabase_service import sb_query, supabase
from services.telephony_yeastar_config_service import (
    load_yeastar_tenant_config,
    yeastar_client_from_config,
)

router = APIRouter(prefix="/api", tags=["telephony"])


def _assert_empresa_access(current_user: CurrentUser, empresa_id: int, *, admin_only: bool = False) -> None:
    if admin_only:
        if not has_global_access(current_user) and str(current_user.empresa_id) != str(empresa_id):
            raise HTTPException(status_code=403, detail="Acceso denegado")
        return
    is_global = has_global_access(current_user)
    if not is_global and str(current_user.empresa_id) != str(empresa_id):
        raise HTTPException(status_code=403, detail="Acceso denegado")


@router.get("/empresas/{empresa_id}/extensions")
async def list_extensions(
    empresa_id: int,
    current_user: CurrentUser = Depends(get_current_user),
):
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión con la base de datos")
    _assert_empresa_access(current_user, empresa_id)

    res = await sb_query(
        lambda eid=empresa_id: supabase.table("yeastar_extensions")
        .select("id, extension_number, extension_name, departamento, created_at, updated_at")
        .eq("empresa_id", eid)
        .order("extension_number")
        .execute()
    )
    return res.data or []


@router.post("/empresas/{empresa_id}/extensions/sync")
async def sync_yeastar_extensions(
    empresa_id: int,
    current_user: CurrentUser = Depends(require_admin),
):
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión con la base de datos")
    _assert_empresa_access(current_user, empresa_id, admin_only=True)

    config = await load_yeastar_tenant_config(empresa_id)
    async with yeastar_client_from_config(config) as client:
        remote_extensions = await client.list_extensions()

    rows = [
        {
            "empresa_id": empresa_id,
            "extension_number": ext["extension_number"],
            "extension_name": ext.get("extension_name"),
            "departamento": ext.get("departamento"),
        }
        for ext in remote_extensions
        if ext.get("extension_number")
    ]

    if rows:
        await sb_query(
            lambda d=rows: supabase.table("yeastar_extensions")
            .upsert(d, on_conflict="empresa_id,extension_number")
            .execute()
        )

    res = await sb_query(
        lambda eid=empresa_id: supabase.table("yeastar_extensions")
        .select("id, extension_number, extension_name, departamento, created_at, updated_at")
        .eq("empresa_id", eid)
        .order("extension_number")
        .execute()
    )
    return {"status": "ok", "synced": len(rows), "extensions": res.data or []}


@router.get("/empresas/{empresa_id}/extensions/statuses")
async def get_yeastar_extension_statuses(
    empresa_id: int,
    current_user: CurrentUser = Depends(require_admin),
):
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión con la base de datos")
    _assert_empresa_access(current_user, empresa_id, admin_only=True)

    ext_res = await sb_query(
        lambda eid=empresa_id: supabase.table("yeastar_extensions")
        .select("extension_number")
        .eq("empresa_id", eid)
        .order("extension_number")
        .execute()
    )
    extensions = [
        str(row.get("extension_number"))
        for row in (ext_res.data or [])
        if row.get("extension_number")
    ]
    config = await load_yeastar_tenant_config(empresa_id)

    statuses: dict[str, str] = {}
    async with yeastar_client_from_config(config) as client:
        for extension in extensions:
            statuses[extension] = await client.get_extension_status(extension)

    return {"statuses": statuses}


@router.post("/empresas/{empresa_id}/extensions", status_code=201)
async def create_extension(
    empresa_id: int,
    payload: dict,
    current_user: CurrentUser = Depends(require_admin),
):
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión con la base de datos")
    _assert_empresa_access(current_user, empresa_id, admin_only=True)

    extension_number = (payload.get("extension_number") or "").strip()
    if not extension_number:
        raise HTTPException(status_code=400, detail="extension_number es obligatorio")

    insert_data = {
        "empresa_id": empresa_id,
        "extension_number": extension_number,
        "extension_name": (payload.get("extension_name") or "").strip() or None,
        "departamento": (payload.get("departamento") or "").strip() or None,
    }
    res = await sb_query(
        lambda d=insert_data: supabase.table("yeastar_extensions").insert(d).execute()
    )
    if not res.data:
        raise HTTPException(status_code=500, detail="Error creando extensión")
    return res.data[0]


@router.put("/empresas/{empresa_id}/extensions/{ext_id}")
async def update_extension(
    empresa_id: int,
    ext_id: str,
    payload: dict,
    current_user: CurrentUser = Depends(require_admin),
):
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión con la base de datos")
    _assert_empresa_access(current_user, empresa_id, admin_only=True)

    update_data: dict = {}
    if "extension_number" in payload:
        update_data["extension_number"] = (payload["extension_number"] or "").strip()
    if "extension_name" in payload:
        update_data["extension_name"] = (payload["extension_name"] or "").strip() or None
    if "departamento" in payload:
        update_data["departamento"] = (payload["departamento"] or "").strip() or None
    if not update_data:
        raise HTTPException(status_code=400, detail="Nada que actualizar")

    await sb_query(
        lambda eid=empresa_id, eid2=ext_id, d=update_data: supabase.table("yeastar_extensions")
        .update(d)
        .eq("empresa_id", eid)
        .eq("id", eid2)
        .execute()
    )
    res = await sb_query(
        lambda eid=empresa_id, eid2=ext_id: supabase.table("yeastar_extensions")
        .select("id, extension_number, extension_name, departamento, created_at")
        .eq("empresa_id", eid)
        .eq("id", eid2)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Extensión no encontrada")
    return res.data[0]


@router.delete("/empresas/{empresa_id}/extensions/{ext_id}", status_code=204)
async def delete_extension(
    empresa_id: int,
    ext_id: str,
    current_user: CurrentUser = Depends(require_admin),
):
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión con la base de datos")
    _assert_empresa_access(current_user, empresa_id, admin_only=True)

    await sb_query(
        lambda eid=empresa_id, eid2=ext_id: supabase.table("yeastar_extensions")
        .delete()
        .eq("empresa_id", eid)
        .eq("id", eid2)
        .execute()
    )
    return None
