"""
telephony.py — Configuración Yeastar PBX, troncales SIP y auto-provision inbound.

Colgar sala, encuestas, outbound y webhooks viven en routers telephony_* dedicados.
"""
from fastapi import APIRouter, Body, Depends, Request, HTTPException
from fastapi.responses import JSONResponse, Response
from models.schemas import (
    YeastarPSeriesConfigCreate,
    YeastarPSeriesConfigResponse,
    YeastarPSeriesConfigTest,
)
from services.supabase_service import supabase, sb_query
from services.platform_access import has_global_access
from services.livekit_service import (
    ensure_citelia_outbound_trunk,
    ensure_yeastar_inbound_trunk,
    list_sip_trunks,
)
from services.yeastar_service import YeastarClient
from services.telephony_room_utils import extract_encuesta_id_from_room
from services.telephony_yeastar_config_service import (
    get_yeastar_config_row as _get_yeastar_config,
    infer_yeastar_api_mode as _infer_yeastar_api_mode,
    load_yeastar_tenant_config as _load_yeastar_tenant_config,
    yeastar_client_from_config as _yeastar_client_from_config,
    yeastar_config_to_response as _yeastar_config_to_response,
)
from services.auth import get_current_user, CurrentUser, require_admin
from services.crypto_service import encrypt_data, decrypt_data
import json
import os
from datetime import datetime, timezone
import logging

logger = logging.getLogger("api-backend")

YEASTAR_API_CAPABILITIES = [
    {
        "id": "system.read",
        "group": "Sistema",
        "label": "Informacion y capacidad PBX",
        "description": "Consultar informacion, capacidad y opciones de menu de la centralita.",
        "permission": "System GET",
        "endpoints": ["GET system/information", "GET system/capacity", "GET system/get_menuoptions"],
        "status": "available",
    },
    {
        "id": "extensions.read",
        "group": "Extensiones",
        "label": "Leer extensiones",
        "description": "Listar, buscar y consultar extensiones para transferencias y directorio.",
        "permission": "Extension GET",
        "endpoints": ["GET extension/list", "GET extension/search", "GET extension/get", "GET extension/query"],
        "status": "implemented",
    },
    {
        "id": "extensions.write",
        "group": "Extensiones",
        "label": "Gestionar extensiones",
        "description": "Crear, editar o eliminar extensiones desde Ausarta.",
        "permission": "Extension POST/GET delete",
        "endpoints": ["POST extension/create", "POST extension/update", "GET extension/delete"],
        "status": "planned",
    },
    {
        "id": "trunks.read",
        "group": "Troncales",
        "label": "Leer troncales",
        "description": "Listar y consultar troncales SIP de Yeastar.",
        "permission": "Trunk GET",
        "endpoints": ["GET trunk/list", "GET trunk/search", "GET trunk/get", "GET trunk/query"],
        "status": "implemented",
    },
    {
        "id": "trunks.write",
        "group": "Troncales",
        "label": "Gestionar troncales SIP",
        "description": "Crear, actualizar o eliminar troncales SIP Yeastar.",
        "permission": "Trunk POST/GET delete",
        "endpoints": ["POST trunk/create", "POST trunk/update", "GET trunk/delete"],
        "status": "planned",
    },
    {
        "id": "routes.read",
        "group": "Rutas",
        "label": "Leer rutas entrantes/salientes",
        "description": "Consultar rutas para auditar enrutamiento de llamadas.",
        "permission": "Inbound Route GET, Outbound Route GET",
        "endpoints": ["GET inbound_route/list", "GET outbound_route/list"],
        "status": "available",
    },
    {
        "id": "routes.write",
        "group": "Rutas",
        "label": "Gestionar rutas",
        "description": "Crear o editar rutas entrantes y salientes.",
        "permission": "Inbound/Outbound Route POST",
        "endpoints": ["POST inbound_route/create", "POST outbound_route/create", "POST outbound_route/update"],
        "status": "planned",
    },
    {
        "id": "contacts.manage",
        "group": "Contactos",
        "label": "Gestionar contactos PBX",
        "description": "Sincronizar contactos de empresa o phonebooks con Yeastar.",
        "permission": "Contacts/Phonebook GET+POST",
        "endpoints": ["GET company_contact/list", "POST company_contact/create", "POST company_contact/update"],
        "status": "available",
    },
    {
        "id": "queues.manage",
        "group": "Colas",
        "label": "Gestionar colas y agentes",
        "description": "Consultar colas, estado de agentes y pausar/reanudar agentes dinamicos.",
        "permission": "Queue GET+POST",
        "endpoints": ["GET queue/query", "GET queue/query_status", "POST queue/pause_agent", "POST queue/unpause_agent"],
        "status": "available",
    },
    {
        "id": "calls.control",
        "group": "Control de llamadas",
        "label": "Controlar llamadas",
        "description": "Transferir, colgar, aparcar, poner en espera, silenciar o reproducir prompts.",
        "permission": "Call Control POST",
        "endpoints": ["POST call/dial", "POST call/transfer", "POST call/hold", "POST call/park", "POST call/play_prompt"],
        "status": "implemented",
    },
    {
        "id": "cdr.recordings",
        "group": "Registros",
        "label": "CDR y grabaciones",
        "description": "Consultar CDR y obtener enlaces de descarga de grabaciones.",
        "permission": "CDR/Recording GET",
        "endpoints": ["GET cdr/list", "GET cdr/search", "GET cdr/download"],
        "status": "available",
    },
    {
        "id": "events.webhooks",
        "group": "Eventos",
        "label": "Webhooks de eventos",
        "description": "Recibir cambios de estado de llamadas, extensiones, CDR y transferencias.",
        "permission": "Event Push / Advanced Settings",
        "endpoints": ["30008 Extension Call State Changed", "30011 Call State Changed", "NewCdr", "CallTransfer"],
        "status": "implemented",
    },
]

# FIX 6 — comprobación de arranque: aviso temprano si falta la variable canónica del trunk
if not os.getenv("SIP_OUTBOUND_TRUNK_ID"):
    logger.critical(
        "SIP_OUTBOUND_TRUNK_ID no configurado — las llamadas salientes fallarán. "
        "Defínelo en .env o en las variables de entorno del contenedor."
    )

router = APIRouter(tags=["telephony"])


def _resolve_ausarta_public_ip() -> str:
    """
    IP pública del servidor Ausarta para whitelist en Yeastar.
    Se lee en runtime del backend (no requiere rebuild del frontend).
    """
    for key in ("AUSARTA_PUBLIC_IP", "VITE_AUSARTA_PUBLIC_IP"):
        val = (os.getenv(key) or "").strip()
        if val and val.lower() not in {"tu.ip.publica.aqui", "changeme"}:
            return val
    return ""


def _resolve_livekit_sip_host() -> tuple[str, int]:
    """
    Host e IP del servidor SIP de LiveKit (livekit-sip) al que Yeastar enviará
    las llamadas entrantes.
    Prioridad: LIVEKIT_SIP_HOST > AUSARTA_PUBLIC_IP (puerto 5070).
    Nota: 5060 está ocupado por Asterisk en el servidor — livekit-sip escucha en 5070.
    Devuelve (host, port).
    """
    explicit = (os.getenv("LIVEKIT_SIP_HOST") or "").strip()
    if explicit:
        if ":" in explicit:
            host, port_str = explicit.rsplit(":", 1)
            try:
                return host.strip(), int(port_str.strip())
            except ValueError:
                pass
        return explicit, 5070

    public_ip = _resolve_ausarta_public_ip()
    if public_ip:
        return public_ip, 5070

    return "", 5070


def _resolve_yeastar_webhook_url() -> str:
    """
    URL pública donde Yeastar envía Event Push (POST /webhooks/yeastar).
    Prioridad: AUSARTA_PUBLIC_WEBHOOK_BASE_URL > FRONTEND_URL + /webhooks/yeastar
    """
    explicit = (os.getenv("AUSARTA_PUBLIC_WEBHOOK_BASE_URL") or "").strip().rstrip("/")
    if explicit:
        if explicit.endswith("/webhooks/yeastar"):
            return explicit
        return f"{explicit}/webhooks/yeastar"

    frontend = (os.getenv("FRONTEND_URL") or os.getenv("INVITE_REDIRECT_TO") or "").strip().rstrip("/")
    if frontend:
        return f"{frontend}/webhooks/yeastar"

    return ""


def _split_yeastar_api_url(raw_url: str) -> tuple[str, int]:
    url = (raw_url or "").strip().rstrip("/")
    if not url:
        return "", 0

    try:
        from urllib.parse import urlparse

        parsed = urlparse(url if "://" in url else f"https://{url}")
        port = parsed.port or 0
        netloc = parsed.hostname or parsed.netloc or url
        scheme = parsed.scheme or "https"
        return f"{scheme}://{netloc}", int(port)
    except Exception:
        return url, 0


def _normalize_yeastar_pbx_url(raw_url: str, api_mode: str) -> tuple[str, int]:
    api_url, parsed_port = _split_yeastar_api_url(raw_url)
    default_port = 443
    return api_url, parsed_port or default_port


@router.get("/api/telephony/platform-info")
async def get_telephony_platform_info(
    current_user: CurrentUser = Depends(require_admin),
):
    """
    Metadatos de plataforma para la pantalla de telefonía (IP whitelist + webhook Yeastar).
    Variables backend: AUSARTA_PUBLIC_IP, AUSARTA_PUBLIC_WEBHOOK_BASE_URL o FRONTEND_URL
    """
    _ = current_user
    return {
        "ausarta_public_ip": _resolve_ausarta_public_ip(),
        "yeastar_webhook_url": _resolve_yeastar_webhook_url(),
    }


@router.get("/api/telephony/yeastar/capabilities")
async def get_yeastar_api_capabilities(
    current_user: CurrentUser = Depends(require_admin),
):
    """Catalogo visible de funciones API Yeastar soportadas/planificadas."""
    _ = current_user
    return {"capabilities": YEASTAR_API_CAPABILITIES}


# ──────────────────────────────────────────────────────────────────────────────
# Yeastar PBX — configuración multi-tenant (P-Series)
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/api/telephony/trunks")
async def get_telephony_trunks(
    empresa_id: int | None = None,
    current_user: CurrentUser = Depends(require_admin),
):
    """
    Lista troncales SIP disponibles en LiveKit y troncales/integraciones Yeastar.
    """
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexiÃ³n con la base de datos")

    target_empresa_id = empresa_id if empresa_id else current_user.empresa_id
    if not target_empresa_id:
        raise HTTPException(status_code=400, detail="empresa_id es obligatorio")

    if target_empresa_id != current_user.empresa_id and not has_global_access(current_user):
        raise HTTPException(status_code=403, detail="No tienes permisos para ver estas troncales")

    livekit_trunks: list[dict] = []
    yeastar_trunks: list[dict] = []
    errors: dict[str, str] = {}

    try:
        livekit_trunks = await list_sip_trunks()
    except Exception as exc:
        logger.warning("[trunks] No se pudieron listar troncales LiveKit: %s", exc)
        errors["livekit"] = str(exc)

    emp_res = await sb_query(
        lambda eid=target_empresa_id: supabase.table("empresas")
        .select("id, nombre")
        .eq("id", eid)
        .limit(1)
        .execute()
    )

    if not emp_res.data:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")

    emp = emp_res.data[0]
    yeastar_config = await _get_yeastar_config(int(emp["id"]))
    if yeastar_config:
        try:
            async with _yeastar_client_from_config(yeastar_config) as client:
                trunks = await client.list_trunks()
            yeastar_trunks = [
                {
                    **trunk,
                    "empresa_id": emp["id"],
                    "empresa_nombre": emp.get("nombre"),
                }
                for trunk in trunks
            ]
        except Exception as exc:
            logger.warning("[trunks] No se pudieron listar troncales Yeastar: %s", exc)
            errors["yeastar"] = str(exc)
            yeastar_trunks = [{
                "provider": "yeastar",
                "id": f"yeastar-config-{emp['id']}",
                "name": emp.get("nombre") or "Yeastar PBX",
                "phone_numbers": [],
                "status": "configured",
                "empresa_id": emp["id"],
                "empresa_nombre": emp.get("nombre"),
                "pbx_url": _yeastar_config_to_response(yeastar_config)["yeastar_pbx_url"],
            }]

    return {
        "livekit_trunks": livekit_trunks,
        "yeastar_trunks": yeastar_trunks,
        "errors": errors,
    }


@router.post("/api/empresas/{empresa_id}/outbound-trunks/citelia")
async def create_citelia_outbound_trunk(
    empresa_id: int,
    payload: dict,
    current_user: CurrentUser = Depends(require_admin),
):
    """
    Crea una troncal saliente LiveKit basada en la plantilla fija CITELIA_SBC.
    Solo superadmin o admin de Ausarta pueden usar este atajo.
    """
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión con la base de datos")

    if not has_global_access(current_user):
        raise HTTPException(status_code=403, detail="Solo Ausarta puede provisionar esta troncal")

    ddi = str(payload.get("ddi") or "").strip()
    if not ddi:
        raise HTTPException(status_code=400, detail="ddi es obligatorio")

    emp_res = await sb_query(
        lambda eid=empresa_id: supabase.table("empresas")
        .select("id, nombre")
        .eq("id", eid)
        .limit(1)
        .execute()
    )
    if not emp_res.data:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")

    empresa = emp_res.data[0]
    trunk = await ensure_citelia_outbound_trunk(
        empresa_id=int(empresa["id"]),
        empresa_nombre=str(empresa.get("nombre") or empresa["id"]),
        ddi=ddi,
    )

    trunk_record = {
        "empresa_id": empresa_id,
        "provider": "CITELIA_SBC",
        "livekit_trunk_id": trunk["id"],
        "ddi": ddi,
        "host": "212.63.112.35:38932",
        "transport": "UDP",
        "domain": "212.63.112.35",
        "is_active": True,
    }
    await sb_query(
        lambda d=trunk_record: supabase.table("empresa_sip_outbound_trunks")
        .upsert(d, on_conflict="empresa_id,provider")
        .execute()
    )

    update_res = await sb_query(
        lambda tid=trunk["id"], eid=empresa_id: supabase.table("empresas")
        .update({"sip_outbound_trunk_id": tid})
        .eq("id", eid)
        .select("id, nombre, sip_outbound_trunk_id, sip_inbound_trunk_id")  # type: ignore[attr-defined]
        .execute()
    )

    return {
        "status": "ok",
        "trunk": trunk,
        "empresa": update_res.data[0] if update_res.data else None,
    }


@router.post("/api/empresas/{empresa_id}/inbound-trunks/sync-yeastar")
async def sync_yeastar_inbound_trunk(
    empresa_id: int,
    payload: dict | None = Body(default=None),
    current_user: CurrentUser = Depends(require_admin),
):
    """Crea/reutiliza inbound LiveKit desde la troncal leida por API Yeastar."""
    if not has_global_access(current_user):
        if not current_user.empresa_id or int(current_user.empresa_id) != int(empresa_id):
            raise HTTPException(status_code=403, detail="No tienes permisos para esta empresa")
    source_trunk_id = str((payload or {}).get("source_trunk_id") or "").strip() or None
    inbound = await _sync_yeastar_inbound_to_livekit(empresa_id, source_trunk_id=source_trunk_id)
    return {"status": "ok", "inbound": inbound}


@router.get("/api/telephony/yeastar", response_model=YeastarPSeriesConfigResponse | None)
async def get_yeastar_config(
    empresa_id: int | None = None,
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Devuelve la configuración Yeastar de la empresa.
    Si empresa_id no se especifica, usa la del usuario autenticado.
    El Client Secret se enmascara si existe.
    """
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión con la base de datos")

    target_empresa_id = empresa_id if empresa_id else current_user.empresa_id
    if target_empresa_id != current_user.empresa_id and not has_global_access(current_user):
        raise HTTPException(status_code=403, detail="No tienes permisos para ver esta configuración")

    if not target_empresa_id:
        raise HTTPException(status_code=403, detail="Usuario sin empresa asignada")

    row = await _get_yeastar_config(int(target_empresa_id))
    if not row:
        return Response(status_code=204)

    return _yeastar_config_to_response(row)


@router.get("/api/empresas/{empresa_id}/yeastar/health")
async def get_yeastar_health(
    empresa_id: int,
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Estado del health-check Yeastar de la empresa y campañas pausadas por salud.

    Multi-tenant: solo la propia empresa o superadmin/platform owner.
    """
    if not has_global_access(current_user):
        if not current_user.empresa_id or int(current_user.empresa_id) != int(empresa_id):
            raise HTTPException(status_code=403, detail="Acceso denegado")

    from services.yeastar_health_service import get_yeastar_health_status
    return await get_yeastar_health_status(empresa_id)


@router.post("/api/empresas/{empresa_id}/yeastar/health/check")
async def force_yeastar_health_check(
    empresa_id: int,
    current_user: CurrentUser = Depends(require_admin),
):
    """
    Fuerza un health-check inmediato para una empresa (operadores / admin).
    Aplica la misma lógica de pausa/reanudación que el cron ARQ.
    """
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión con la base de datos")
    if not has_global_access(current_user):
        if not current_user.empresa_id or int(current_user.empresa_id) != int(empresa_id):
            raise HTTPException(status_code=403, detail="Acceso denegado")

    row = await _get_yeastar_config(empresa_id)
    if not row:
        raise HTTPException(status_code=404, detail="Yeastar no configurado para esta empresa")

    from services.yeastar_health_service import check_single_empresa_health
    result = await check_single_empresa_health(row)
    return {"status": "ok", "result": result}


@router.post("/api/telephony/yeastar", response_model=YeastarPSeriesConfigResponse)
async def save_yeastar_config(
    payload: YeastarPSeriesConfigCreate,
    current_user: CurrentUser = Depends(require_admin),
):
    """
    Guarda la configuración Yeastar de la empresa en la tabla empresas.
    Solo accesible para roles admin y superadmin.
    """
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión con la base de datos")

    target_empresa_id = payload.empresa_id if payload.empresa_id else current_user.empresa_id
    if target_empresa_id != current_user.empresa_id and not has_global_access(current_user):
        raise HTTPException(status_code=403, detail="No tienes permisos para editar esta configuración")

    if not target_empresa_id:
        raise HTTPException(status_code=403, detail="Usuario sin empresa asignada")

    existing_config = await _get_yeastar_config(int(target_empresa_id))
    api_mode = _infer_yeastar_api_mode(payload.yeastar_pbx_url, payload.yeastar_api_mode)
    api_url, api_port = _normalize_yeastar_pbx_url(payload.yeastar_pbx_url, api_mode)
    update_data = {
        "empresa_id": target_empresa_id,
        "api_url": api_url,
        "api_port": api_port,
        "api_mode": api_mode,
        "api_username": payload.yeastar_client_id.strip(),
        "is_active": True,
        "enabled_capabilities": payload.enabled_capabilities or [],
    }
    if payload.ddi:
        update_data["ddi"] = payload.ddi.strip()

    if payload.yeastar_client_secret and payload.yeastar_client_secret != "********":
        try:
            update_data["api_password"] = encrypt_data(payload.yeastar_client_secret.strip())
        except ValueError as exc:
            raise HTTPException(
                status_code=503,
                detail="No se puede guardar el Client Secret: ENCRYPTION_KEY no esta configurada en el backend.",
            ) from exc
    elif existing_config and existing_config.get("api_password"):
        update_data["api_password"] = existing_config["api_password"]
    else:
        raise HTTPException(status_code=400, detail="Client Secret es obligatorio para una configuraciÃ³n nueva")

    await sb_query(
        lambda d=update_data: supabase.table("company_yeastar_configs")
        .upsert(d, on_conflict="empresa_id")
        .execute()
    )

    row = await _get_yeastar_config(int(target_empresa_id))
    if not row:
        raise HTTPException(status_code=500, detail="Error al guardar la configuración Yeastar")

    try:
        await _sync_yeastar_inbound_to_livekit(int(target_empresa_id))
    except Exception as exc:
        logger.warning(
            "[yeastar-inbound] Config guardada, pero no se pudo sincronizar inbound empresa=%s: %s",
            target_empresa_id,
            exc,
        )

    # Configurar automáticamente el Yeastar del cliente por API
    auto_config_result: dict = {}
    try:
        auto_config_result = await _auto_configure_yeastar(
            empresa_id=int(target_empresa_id),
            ddi=payload.ddi,
        )
        if auto_config_result.get("errors"):
            logger.warning(
                "[auto-config] empresa=%s configuración parcial: %s",
                target_empresa_id,
                auto_config_result["errors"],
            )
        else:
            logger.info(
                "[auto-config] empresa=%s configuración Yeastar completada OK",
                target_empresa_id,
            )
    except Exception as exc:
        logger.warning(
            "[auto-config] empresa=%s error inesperado: %s",
            target_empresa_id,
            exc,
        )

    response_data = _yeastar_config_to_response(row)
    return {**response_data, "auto_config_result": auto_config_result}


@router.post("/api/telephony/yeastar/test")
async def test_yeastar_connection(
    payload: YeastarPSeriesConfigTest,
    current_user: CurrentUser = Depends(require_admin),
):
    """
    Prueba la conexión con la centralita Yeastar usando las credenciales
    proporcionadas en tiempo real.
    """
    client_secret = payload.yeastar_client_secret
    target_empresa_id = payload.empresa_id if payload.empresa_id else current_user.empresa_id
    if not target_empresa_id:
        raise HTTPException(status_code=403, detail="Usuario sin empresa asignada")
    if target_empresa_id != current_user.empresa_id and not has_global_access(current_user):
        raise HTTPException(status_code=403, detail="No tienes permisos para probar esta centralita")

    # If masked, we need to fetch the real secret from DB
    if client_secret == "********":
        res = await sb_query(
            lambda: supabase.table("company_yeastar_configs")
            .select("api_password")
            .eq("empresa_id", target_empresa_id)
            .limit(1)
            .execute()
        )
        if res.data and res.data[0].get("api_password"):
            # Hardening: Decrypt secret from DB for testing
            client_secret = decrypt_data(res.data[0]["api_password"])
        else:
            return {"ok": False, "message": "No se encontró el secreto original en la base de datos."}
    else:
        # If it's a new secret being tested, use it as is (will be encrypted on save)
        pass

    api_mode = _infer_yeastar_api_mode(payload.yeastar_pbx_url, payload.yeastar_api_mode)
    async with YeastarClient(
        pbx_url=payload.yeastar_pbx_url,
        api_mode=api_mode,
        client_id=payload.yeastar_client_id,
        client_secret=client_secret,
        tenant_id=target_empresa_id,
    ) as client:
        ok, message = await client.test_connection()
    return {"ok": ok, "message": message}


async def _resolve_survey_id(room_name: str, survey_id: int | None) -> int:
    """Obtiene survey_id del body o extrayéndolo del nombre de sala LiveKit."""
    if survey_id:
        return survey_id
    extracted = extract_encuesta_id_from_room(room_name.strip())
    if extracted:
        return extracted
    raise HTTPException(
        status_code=400,
        detail="No se pudo determinar survey_id. Envíe survey_id o un room_name válido (ej. ..._encuesta_123).",
    )


async def _sync_yeastar_inbound_to_livekit(empresa_id: int, source_trunk_id: str | None = None) -> dict:
    """Provisiona inbound LiveKit y guarda su ID usando la troncal Yeastar."""
    emp_res = await sb_query(
        lambda eid=empresa_id: supabase.table("empresas")
        .select("id,nombre")
        .eq("id", eid)
        .limit(1)
        .execute()
    )
    if not emp_res.data:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")

    config = await _load_yeastar_tenant_config(empresa_id)
    async with _yeastar_client_from_config(config) as client:
        trunks = await client.list_trunks()
    if not trunks:
        raise HTTPException(status_code=409, detail="Yeastar no tiene ninguna troncal disponible")

    if source_trunk_id:
        trunk = next(
            (
                item for item in trunks
                if str(item.get("id") or "") == source_trunk_id
                or str(item.get("name") or "") == source_trunk_id
            ),
            None,
        )
        if not trunk:
            raise HTTPException(status_code=404, detail="La troncal Yeastar seleccionada no existe")
    else:
        trunk = next(
            (item for item in trunks if str(item.get("status")) in {"1", "available", "active"}),
            trunks[0],
        )
    addresses = [str(trunk.get("address") or "").strip()]
    try:
        import socket
        from urllib.parse import urlparse

        hostname = urlparse(str(config.get("api_url") or "")).hostname
        if hostname:
            addresses.append(socket.gethostbyname(hostname))
    except Exception as exc:
        logger.warning("[yeastar-inbound] No se pudo resolver IP PBX: %s", exc)

    outbound_res = await sb_query(
        lambda eid=empresa_id: supabase.table("empresa_sip_outbound_trunks")
        .select("ddi")
        .eq("empresa_id", eid)
        .eq("is_active", True)
        .execute()
    )
    numbers = list(trunk.get("phone_numbers") or [])
    numbers.extend(row.get("ddi") for row in (outbound_res.data or []) if row.get("ddi"))
    inbound_agent_id = await _resolve_inbound_agent_id(empresa_id)

    inbound = await ensure_yeastar_inbound_trunk(
        empresa_id=empresa_id,
        empresa_nombre=str(emp_res.data[0].get("nombre") or empresa_id),
        allowed_addresses=addresses,
        numbers=numbers,
        inbound_agent_id=inbound_agent_id,
    )
    await sb_query(
        lambda tid=inbound["id"], eid=empresa_id: supabase.table("empresas")
        .update({"sip_inbound_trunk_id": tid})
        .eq("id", eid)
        .execute()
    )
    return {**inbound, "source_trunk": trunk, "candidate_addresses": addresses}


async def _auto_configure_yeastar(empresa_id: int, ddi: str | None) -> dict:
    """
    Configura automáticamente el Yeastar del cliente:
      1. Crea (o reutiliza) la troncal SIP hacia LiveKit en el Yeastar del cliente.
      2. Crea la ruta entrante DDI → esa troncal.
      3. Configura Event Push → /webhooks/yeastar de Ausarta.

    Se llama tras save_yeastar_config. Fallos no bloquean el guardado
    (se loguean como warning y se devuelven en auto_config_result.errors).
    """
    result: dict = {"sip_trunk": None, "inbound_route": None, "event_push": None, "errors": []}

    config = await _get_yeastar_config(int(empresa_id))
    if not config:
        result["errors"].append("Config Yeastar no encontrada tras guardar")
        return result

    webhook_url = _resolve_yeastar_webhook_url()
    if not webhook_url:
        result["errors"].append(
            "AUSARTA_PUBLIC_WEBHOOK_BASE_URL o FRONTEND_URL no configurados — "
            "no se puede apuntar el Event Push"
        )

    livekit_sip_host, livekit_sip_port = _resolve_livekit_sip_host()
    livekit_trunk_name = "ausarta_livekit"

    async with _yeastar_client_from_config(config) as client:
        # --- 1. Crear troncal SIP hacia LiveKit ---
        if livekit_sip_host:
            try:
                result["sip_trunk"] = await client.create_sip_trunk(
                    trunk_name=livekit_trunk_name,
                    host=livekit_sip_host,
                    port=livekit_sip_port,
                    ddi=ddi,
                )
            except Exception as exc:
                msg = f"Troncal SIP LiveKit falló: {exc}"
                logger.warning("[auto-config] empresa=%s %s", empresa_id, msg)
                result["errors"].append(msg)
        else:
            result["errors"].append(
                "LIVEKIT_SIP_HOST o AUSARTA_PUBLIC_IP no configurados — "
                "no se puede crear la troncal SIP en el Yeastar del cliente"
            )

        # --- 2. Event Push ---
        if webhook_url:
            try:
                result["event_push"] = await client.configure_event_push(webhook_url)
            except Exception as exc:
                msg = f"Event Push falló: {exc}"
                logger.warning("[auto-config] empresa=%s %s", empresa_id, msg)
                result["errors"].append(msg)

        # --- 3. Ruta entrante DDI → troncal LiveKit ---
        if not ddi:
            try:
                ddi = str(config.get("ddi") or "").strip() or None
            except Exception:
                pass

        if ddi:
            try:
                # Usar la troncal que acabamos de crear/verificar, o buscar una existente
                trunk_for_route = livekit_trunk_name
                if result["sip_trunk"] is None:
                    # La creación falló — intentar encontrar una existente con keywords LiveKit
                    trunks = await client.list_trunks()
                    found = next(
                        (
                            t for t in trunks
                            if any(
                                kw in str(t.get("name", "")).lower()
                                for kw in ("livekit", "ausarta", "sip_out", "sbc")
                            )
                        ),
                        None,
                    )
                    if found:
                        trunk_for_route = str(found["name"])
                    else:
                        result["errors"].append(
                            "No se encontró troncal SIP hacia LiveKit — ruta entrante no creada."
                        )
                        trunk_for_route = None

                if trunk_for_route:
                    result["inbound_route"] = await client.create_inbound_route(
                        ddi=ddi,
                        trunk_name=trunk_for_route,
                    )
            except Exception as exc:
                msg = f"Ruta entrante falló: {exc}"
                logger.warning("[auto-config] empresa=%s %s", empresa_id, msg)
                result["errors"].append(msg)
        else:
            result["errors"].append(
                "DDI no proporcionado — ruta entrante no creada. "
                "Pasa el campo 'ddi' en el payload para crearla automáticamente."
            )

    return result


async def _resolve_inbound_agent_id(empresa_id: int) -> int | None:
    """Devuelve el agente preferido para llamadas entrantes de una empresa."""
    res = await sb_query(
        lambda eid=empresa_id: supabase.table("agent_config")
        .select("id,name,agent_type,tipo_resultados")
        .eq("empresa_id", eid)
        .order("id")
        .execute()
    )
    agents = res.data or []
    if not agents:
        return None
    preferred = next(
        (
            agent for agent in agents
            if "inbound" in str(agent.get("name") or "").lower()
            or "recepcion" in str(agent.get("name") or "").lower()
            or str(agent.get("agent_type") or agent.get("tipo_resultados") or "").upper() == "SOPORTE_CLIENTE"
        ),
        agents[0],
    )
    return int(preferred["id"]) if preferred.get("id") is not None else None

