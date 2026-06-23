"""Helpers compartidos de configuración Yeastar por empresa."""

from __future__ import annotations

from fastapi import HTTPException

from services.crypto_service import decrypt_data
from services.supabase_service import sb_query, supabase
from services.yeastar_service import YeastarApiMode, YeastarClient


async def get_yeastar_config_row(empresa_id: int) -> dict | None:
    res = await sb_query(
        lambda eid=empresa_id: supabase.table("company_yeastar_configs")
        .select(
            "id, empresa_id, api_url, api_port, api_mode, api_username, api_password, "
            "is_active, enabled_capabilities, created_at, updated_at"
        )
        .eq("empresa_id", eid)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def yeastar_config_to_response(row: dict) -> dict:
    api_url = str(row.get("api_url") or "").rstrip("/")
    api_mode = str(row.get("api_mode") or "pseries")
    default_port = 443
    api_port = int(row.get("api_port") or default_port)
    tail = api_url.rsplit("/", 1)[-1]
    yeastar_pbx_url = f"{api_url}:{api_port}" if api_url and f":{api_port}" not in tail else api_url
    return {
        "empresa_id": int(row["empresa_id"]),
        "yeastar_pbx_url": yeastar_pbx_url,
        "yeastar_api_mode": api_mode,
        "yeastar_client_id": row.get("api_username") or "",
        "yeastar_client_secret": "********" if row.get("api_password") else "",
        "enabled_capabilities": list(row.get("enabled_capabilities") or []),
        "ddi": row.get("ddi") or "",
    }


def infer_yeastar_api_mode(raw_url: str, explicit_mode: str | None = None) -> YeastarApiMode:
    mode = (explicit_mode or "").strip().lower()
    if mode == "cloud_pbx":
        return "cloud_pbx"
    if mode == "pseries":
        return "pseries"
    url = (raw_url or "").strip().lower()
    if ".cloud." in url or "yeastarcloud" in url:
        return "cloud_pbx"
    return "pseries"


def yeastar_client_from_config(row: dict) -> YeastarClient:
    api_url = str(row.get("api_url") or "").rstrip("/")
    api_mode = infer_yeastar_api_mode(api_url, row.get("api_mode"))
    default_port = 443
    api_port = int(row.get("api_port") or default_port)
    tail = api_url.rsplit("/", 1)[-1]
    pbx_url = f"{api_url}:{api_port}" if api_url and f":{api_port}" not in tail else api_url
    return YeastarClient(
        pbx_url=pbx_url,
        api_mode=api_mode,
        client_id=str(row.get("api_username") or ""),
        client_secret=decrypt_data(row.get("api_password") or ""),
        tenant_id=row.get("empresa_id"),
    )


async def load_yeastar_tenant_config(empresa_id: int) -> dict:
    emp_res = await sb_query(
        lambda eid=empresa_id: supabase.table("empresas")
        .select("id")
        .eq("id", eid)
        .limit(1)
        .execute()
    )
    if not emp_res.data:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")

    config = await get_yeastar_config_row(int(empresa_id))
    if not config:
        raise HTTPException(
            status_code=400,
            detail="Centralita Yeastar no configurada para esta empresa",
        )
    if not config.get("api_password"):
        raise HTTPException(status_code=400, detail="Credenciales Yeastar incompletas")
    return config
