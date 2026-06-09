"""
telephony.py — Gestión de llamadas, webhooks entrantes e integración Yeastar PBX.

Responsabilidades:
  - /colgar: cierra una sala de LiveKit.
  - /guardar-encuesta: persiste datos de una encuesta y propaga estado a campaign_leads.
  - /api/calls/outbound: inicia una llamada SIP individual (test o desde campaña).
  - /api/livekit/webhook: recibe eventos de LiveKit (room_finished, participant_left)
    para actualizar el estado de los leads sin polling.
  - /api/telephony/yeastar: CRUD de la configuración Yeastar PBX por empresa.
  - /api/telephony/yeastar/test: prueba la conexión en tiempo real sin persistir.
  - /api/calls/transfer: transferencia multi-tenant a agente humano (Yeastar).
  - /api/telephony/transfer: alias legacy del endpoint de transferencia.
"""
from fastapi import APIRouter, BackgroundTasks, Body, Depends, Request, HTTPException
from fastapi.responses import JSONResponse, Response
from models.schemas import (
    CallEndRequest,
    CallTransferRequest,
    EncuestaData,
    TelephonyTransferRequest,
    TestOutboundCallRequest,
    YeastarPSeriesConfigCreate,
    YeastarPSeriesConfigResponse,
    YeastarPSeriesConfigTest,
)
from services.supabase_service import supabase, sb_query
from services.platform_access import has_global_access
from services.livekit_service import (
    lkapi,
    create_isolated_room,
    create_outbound_call,
    dispatch_agent_explicit,
    ensure_citelia_outbound_trunk,
    ensure_yeastar_inbound_trunk,
    list_sip_trunks,
    wait_for_agent_ready,
)
from services.yeastar_service import YeastarClient
from services.yeastar_webhook_service import (
    normalize_yeastar_webhook_payload,
    process_yeastar_webhook_payload,
)
from services.trunk_service import resolve_outbound_trunk_id
from services.auth import get_current_user, CurrentUser, require_admin, require_outbound_auth
from services.crypto_service import encrypt_data, decrypt_data
from services.rate_limiter import limiter
from services.queue_service import get_arq_pool
from livekit import api
from livekit.api import WebhookReceiver
import aiohttp
import asyncio
import os
from datetime import datetime, timedelta, timezone
import random
import logging

# Credenciales LiveKit para validar firmas de webhooks entrantes
_LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY", "")
_LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET", "")

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


def _normalize_test_outbound_phone(raw: str) -> str:
    """Convierte números españoles sin prefijo a E.164 (+34…)."""
    s = (raw or "").strip()
    if not s:
        return ""
    if s.startswith("+"):
        return s
    digits = "".join(c for c in s if c.isdigit())
    if len(digits) == 9 and digits[0] in "6789":
        return f"+34{digits}"
    if len(digits) == 11 and digits.startswith("34"):
        return f"+{digits}"
    return s


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


async def _get_yeastar_config(empresa_id: int) -> dict | None:
    res = await sb_query(
        lambda eid=empresa_id: supabase.table("company_yeastar_configs")
        .select("id, empresa_id, api_url, api_port, api_mode, api_username, api_password, is_active, enabled_capabilities, created_at, updated_at")
        .eq("empresa_id", eid)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def _yeastar_config_to_response(row: dict) -> dict:
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
    }


def _infer_yeastar_api_mode(raw_url: str, explicit_mode: str | None = None) -> str:
    mode = (explicit_mode or "").strip().lower()
    if mode in {"pseries", "cloud_pbx"}:
        return mode
    url = (raw_url or "").strip().lower()
    if ".cloud." in url or "yeastarcloud" in url:
        return "cloud_pbx"
    return "pseries"


def _yeastar_client_from_config(row: dict) -> YeastarClient:
    api_url = str(row.get("api_url") or "").rstrip("/")
    api_mode = _infer_yeastar_api_mode(api_url, row.get("api_mode"))
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


async def _resolve_test_outbound_context(payload: TestOutboundCallRequest) -> tuple[str, str, int]:
    """
    Resuelve empresa + encuesta (ID fila encuestas) + campaign_id para el dispatch del agente.
    El worker LiveKit exige survey_id ≠ 0 y presencia de campana_id/client_id en metadata del job.
    """
    if not supabase:
        raise HTTPException(status_code=503, detail="Supabase no disponible")

    from_name = (payload.from_empresa_nombre or "").strip()
    empresa_hint = (payload.empresa_id or "").strip()

    empresa_id_int: int | None = None
    if empresa_hint.isdigit():
        empresa_id_int = int(empresa_hint)

    if from_name:
        emp_res = await sb_query(lambda: supabase.table("empresas").select("id,nombre").execute())
        want = from_name.casefold()
        candidates = emp_res.data or []
        exact = next(
            (r for r in candidates if str(r.get("nombre") or "").strip().casefold() == want),
            None,
        )
        partial = next(
            (r for r in candidates if want in str(r.get("nombre") or "").strip().casefold()),
            None,
        )
        picked = exact or partial
        if not picked:
            raise HTTPException(
                status_code=404,
                detail=f"Empresa no encontrada por nombre: {from_name}",
            )
        resolved = int(picked["id"])
        if empresa_id_int is not None and empresa_id_int != resolved:
            logger.warning(
                "[test-outbound] empresa_id (%s) no coincide con from_empresa_nombre='%s' (id=%s); "
                "se usa la empresa resuelta por nombre.",
                empresa_id_int,
                from_name,
                resolved,
            )
        empresa_id_int = resolved

    if empresa_id_int is None:
        raise HTTPException(
            status_code=400,
            detail="empresa_id o from_empresa_nombre es obligatorio",
        )

    survey_hint = (payload.survey_id or "").strip()

    survey_id_int: int | None = None
    campaign_id_int = 0

    if survey_hint.isdigit() and int(survey_hint) > 0:
        survey_id_int = int(survey_hint)
        chk = await sb_query(
            lambda sid=survey_id_int: supabase.table("encuestas")
            .select("id, empresa_id, campaign_id, agent_id")
            .eq("id", sid)
            .limit(1)
            .execute()
        )
        row = chk.data[0] if chk.data else None
        if not row:
            raise HTTPException(status_code=404, detail=f"Encuesta id={survey_id_int} no encontrada")
        if row.get("empresa_id") != empresa_id_int:
            raise HTTPException(
                status_code=400,
                detail="survey_id no pertenece a la empresa indicada",
            )
        if row.get("agent_id") is None:
            raise HTTPException(
                status_code=400,
                detail="Esa encuesta no tiene agent_id; elige otra o deja survey_id vacío para autoselección",
            )
        campaign_id_int = int(row["campaign_id"] or 0)
    else:
        enc_res = await sb_query(
            lambda eid=empresa_id_int: supabase.table("encuestas")
            .select("id,campaign_id")
            .eq("empresa_id", eid)
            .not_.is_("agent_id", "null")
            .order("id", desc=True)
            .limit(1)
            .execute()
        )
        rows = enc_res.data or []
        if not rows:
            raise HTTPException(
                status_code=400,
                detail="No hay encuestas con agente asignado para esa empresa — indica survey_id explícito",
            )
        survey_id_int = int(rows[0]["id"])
        campaign_id_int = int(rows[0].get("campaign_id") or 0)

    empresa_str = str(empresa_id_int)
    survey_str = str(survey_id_int)
    logger.info(
        "[test-outbound] Contexto resuelto: empresa_id=%s encuesta_id=%s campaign_id=%s",
        empresa_str,
        survey_str,
        campaign_id_int,
    )
    return empresa_str, survey_str, campaign_id_int


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
        .select("id, nombre, sip_outbound_trunk_id, sip_inbound_trunk_id")
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

    return _yeastar_config_to_response(row)


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


def _parse_datos_extra(raw: object) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            import json as _json
            parsed = _json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


async def _resolve_survey_id(room_name: str, survey_id: int | None) -> int:
    """Obtiene survey_id del body o extrayéndolo del nombre de sala LiveKit."""
    if survey_id:
        return survey_id
    extracted = _extract_encuesta_id_from_room(room_name.strip())
    if extracted:
        return extracted
    raise HTTPException(
        status_code=400,
        detail="No se pudo determinar survey_id. Envíe survey_id o un room_name válido (ej. ..._encuesta_123).",
    )


async def _load_yeastar_tenant_config(empresa_id: int) -> dict:
    """
    Credenciales Yeastar del tenant (tabla company_yeastar_configs).
    target_extension: variable de entorno global o datos_extra de la encuesta.
    """
    emp_res = await sb_query(
        lambda eid=empresa_id: supabase.table("empresas")
        .select("id")
        .eq("id", eid)
        .limit(1)
        .execute()
    )
    if not emp_res.data:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")

    config = await _get_yeastar_config(int(empresa_id))
    if not config:
        raise HTTPException(
            status_code=400,
            detail="Centralita Yeastar no configurada para esta empresa",
        )
    if not config.get("api_password"):
        raise HTTPException(status_code=400, detail="Credenciales Yeastar incompletas")

    return config


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


def _resolve_target_extension(
    datos_extra: dict,
    explicit: str | None = None,
) -> str:
    ext = (
        (explicit or "").strip()
        or (os.getenv("YEASTAR_HUMAN_TRANSFER_EXTENSION") or "").strip()
        or str(datos_extra.get("target_extension") or "").strip()
        or str(datos_extra.get("human_transfer_extension") or "").strip()
    )
    if not ext:
        raise HTTPException(
            status_code=400,
            detail="Extensión de transferencia no configurada (YEASTAR_HUMAN_TRANSFER_EXTENSION).",
        )
    return ext


async def _execute_yeastar_transfer(
    *,
    room_name: str,
    survey_id: int,
    motivo: str | None = None,
    call_id: str | None = None,
    target_extension: str | None = None,
    yeastar_call_id: str | None = None,
) -> dict:
    """Lógica compartida de transferencia multi-tenant vía Yeastar P-Series."""
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión con la base de datos")

    room_name = room_name.strip()

    enc_res = await sb_query(
        lambda sid=survey_id: supabase.table("encuestas")
        .select("id, empresa_id, telefono, datos_extra, status")
        .eq("id", sid)
        .limit(1)
        .execute()
    )
    if not enc_res.data:
        raise HTTPException(status_code=404, detail=f"Encuesta {survey_id} no encontrada")

    enc = enc_res.data[0]
    empresa_id = enc.get("empresa_id")
    if not empresa_id:
        logger.error(f"[transfer] Encuesta {survey_id} sin empresa_id (room={room_name})")
        raise HTTPException(status_code=400, detail="Encuesta sin empresa asociada")

    emp = await _load_yeastar_tenant_config(empresa_id)
    datos_extra = _parse_datos_extra(enc.get("datos_extra"))

    resolved_call_id = (
        call_id
        or yeastar_call_id
        or datos_extra.get("yeastar_callid")
        or datos_extra.get("yeastar_call_id")
        or room_name
    )
    resolved_channel_id = str(datos_extra.get("yeastar_channel_id") or "").strip()
    if not resolved_channel_id:
        raise HTTPException(
            status_code=409,
            detail="Falta yeastar_channel_id del webhook 30011 para transferir la llamada.",
        )
    resolved_extension = _resolve_target_extension(datos_extra, target_extension)

    try:
        async with _yeastar_client_from_config(emp) as client:
            await client.transfer_call(resolved_channel_id, resolved_extension)
    except Exception as exc:
        logger.error(
            f"[transfer] Fallo Yeastar empresa={empresa_id} survey={survey_id} "
            f"room={room_name} call_id={resolved_call_id}: {exc}"
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    motivo_text = (motivo or "Transferencia a agente humano").strip()
    merged_extra = {
        **datos_extra,
        "transfer_room": room_name,
        "transfer_extension": resolved_extension,
        "yeastar_callid": str(resolved_call_id),
    }
    await sb_query(
        lambda sid=survey_id, extra=merged_extra, m=motivo_text, ext=resolved_extension: supabase.table("encuestas")
        .update({
            "status": "transferred",
            "comentarios": f"Transferido a ext {ext}: {m}",
            "datos_extra": extra,
        })
        .eq("id", sid)
        .execute()
    )

    logger.info(
        f"✅ [transfer] empresa={empresa_id} survey={survey_id} "
        f"call_id={resolved_call_id} → ext {resolved_extension} room={room_name}"
    )
    return {
        "status": "ok",
        "message": "Transferencia iniciada en la centralita",
        "empresa_id": empresa_id,
        "survey_id": survey_id,
        "room_name": room_name,
        "call_id": str(resolved_call_id),
        "target_extension": resolved_extension,
    }


@router.post("/api/calls/transfer")
async def transfer_call_to_human(payload: CallTransferRequest):
    """
    Transfiere una llamada a extensión humana tras comprobar que está Idle en Yeastar.

    Body: ``room_name``, ``empresa_id``, ``call_id``, ``extension`` (default 1000).
    """
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión con la base de datos")

    room_name = payload.room_name.strip()
    if not room_name:
        raise HTTPException(status_code=400, detail="room_name es obligatorio")

    if not payload.empresa_id:
        raise HTTPException(status_code=400, detail="empresa_id es obligatorio")

    call_id = (payload.call_id or "").strip()
    survey_id = payload.survey_id or _extract_encuesta_id_from_room(room_name)
    datos_extra: dict = {}
    if survey_id:
        enc_res = await sb_query(
            lambda sid=survey_id: supabase.table("encuestas")
            .select("datos_extra")
            .eq("id", sid)
            .limit(1)
            .execute()
        )
        datos_extra = _parse_datos_extra(
            enc_res.data[0].get("datos_extra") if enc_res.data else {}
        )
        call_id = str(
            datos_extra.get("yeastar_callid")
            or datos_extra.get("yeastar_call_id")
            or call_id
        ).strip()
    channel_id = str(datos_extra.get("yeastar_channel_id") or "").strip()
    if not call_id:
        raise HTTPException(status_code=400, detail="call_id es obligatorio")
    if call_id == room_name:
        raise HTTPException(
            status_code=409,
            detail=(
                "La llamada no tiene call_id de Yeastar. Solo se puede transferir a una "
                "extension interna si la llamada ha pasado por Yeastar y se ha recibido "
                "el webhook 30011."
            ),
        )
    if not channel_id:
        raise HTTPException(
            status_code=409,
            detail=(
                "La llamada no tiene channel_id de Yeastar. Comprueba que el webhook "
                "30011 Call State Changed esta activo antes de intentar transferir."
            ),
        )

    extension = (payload.extension or "1000").strip()
    empresa_id = int(payload.empresa_id)

    config = await _load_yeastar_tenant_config(empresa_id)

    try:
        async with _yeastar_client_from_config(config) as yeastar_client:
            ext_status = await yeastar_client.get_extension_status(extension)
            if str(ext_status).strip().lower() not in {"idle", "available"}:
                logger.info(
                    f"[transfer] ExtensiÃ³n {extension} no disponible (status={ext_status}) "
                    f"empresa={empresa_id} room={room_name}"
                )
                return JSONResponse(
                    status_code=409,
                    content={
                        "message": f"ExtensiÃ³n ocupada ({ext_status})",
                        "status": ext_status,
                    },
                )

            await yeastar_client.transfer_call(channel_id, extension)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            f"[transfer] Error Yeastar empresa={empresa_id} call_id={call_id}: {exc}"
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if False:
            logger.info(
                f"[transfer] Extensión {extension} no disponible (status={ext_status}) "
                f"empresa={empresa_id} room={room_name}"
            )
            return JSONResponse(
                status_code=409,
                content={
                    "message": f"Extensión ocupada ({ext_status})",
                    "status": ext_status,
                },
            )

    if survey_id:
        motivo_text = (payload.motivo or "Transferencia a agente humano").strip()
        try:
            enc_res = await sb_query(
                lambda sid=survey_id: supabase.table("encuestas")
                .select("datos_extra")
                .eq("id", sid)
                .limit(1)
                .execute()
            )
            datos_extra = _parse_datos_extra(
                enc_res.data[0].get("datos_extra") if enc_res.data else {}
            )
            merged_extra = {
                **datos_extra,
                "transfer_room": room_name,
                "transfer_extension": extension,
                "yeastar_callid": call_id,
            }
            await sb_query(
                lambda sid=survey_id, extra=merged_extra, m=motivo_text, ext=extension: supabase.table("encuestas")
                .update({
                    "status": "transferred",
                    "comentarios": f"Transferido a ext {ext}: {m}",
                    "datos_extra": extra,
                })
                .eq("id", sid)
                .execute()
            )
        except Exception as db_err:
            logger.warning(f"[transfer] No se pudo actualizar encuesta {survey_id}: {db_err}")

    logger.info(
        f"✅ [transfer] empresa={empresa_id} call_id={call_id} → ext {extension} room={room_name}"
    )
    return {
        "status": "ok",
        "message": "Transferencia iniciada en la centralita",
        "empresa_id": empresa_id,
        "room_name": room_name,
        "call_id": call_id,
        "extension": extension,
        "extension_status": ext_status,
    }


@router.get("/api/calls/{encuesta_id}/briefing")
async def get_call_transfer_briefing(
    encuesta_id: int,
    current_user: CurrentUser = Depends(get_current_user),
):
    """Devuelve el transfer_briefing asociado a una encuesta."""
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión con la base de datos")

    res = await sb_query(
        lambda sid=encuesta_id: supabase.table("encuestas")
        .select("id, empresa_id, transfer_briefing, datos_extra")
        .eq("id", sid)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Encuesta no encontrada")

    row = res.data[0]
    empresa_id = int(row.get("empresa_id") or 0)
    if not has_global_access(current_user) and int(current_user.empresa_id or 0) != empresa_id:
        raise HTTPException(status_code=403, detail="Acceso denegado")

    datos_extra = _parse_datos_extra(row.get("datos_extra") or {})
    briefing = row.get("transfer_briefing") or datos_extra.get("transfer_briefing") or ""
    return {"encuesta_id": encuesta_id, "transfer_briefing": briefing}


@router.post("/api/telephony/transfer")
async def transfer_call_to_human_legacy(payload: TelephonyTransferRequest):
    """Alias legacy; prefiere call_id de Yeastar si está en BD."""
    return await _execute_yeastar_transfer(
        room_name=payload.room_name.strip(),
        survey_id=payload.survey_id,
        motivo=payload.motivo,
        call_id=None,
        target_extension=payload.target_extension,
        yeastar_call_id=payload.yeastar_call_id,
    )

# Hardening: IP Whitelist for Yeastar Webhooks (example placeholder)
YEASTAR_IP_WHITELIST = os.getenv("YEASTAR_IP_WHITELIST", "").split(",")

async def validate_yeastar_ip(request: Request):
    """Optional: Validates that the request comes from a trusted Yeastar PBX IP."""
    if not YEASTAR_IP_WHITELIST or YEASTAR_IP_WHITELIST == [""]:
        return # Whitelist not configured, skip validation
    
    client_ip = request.client.host
    if client_ip not in YEASTAR_IP_WHITELIST:
        logger.warning(f"🛡️ [Security] Blocked unauthorized webhook attempt from IP: {client_ip}")
        raise HTTPException(status_code=403, detail="Unauthorized IP")

@limiter.exempt
@router.post("/webhooks/yeastar")
async def yeastar_webhook(
    request: Request,
    _=Depends(validate_yeastar_ip),  # Bloquea IPs no autorizadas si YEASTAR_IP_WHITELIST está configurado
):
    """
    Recibe eventos de la centralita Yeastar (CallAnswered, CallHangup, etc.).
    Optimización: Procesa en segundo plano para evitar timeouts de la PBX.
    """
    try:
        payload = await request.json()

        arq_pool = await get_arq_pool()
        job = await arq_pool.enqueue_job("process_yeastar_webhook", payload)

        return {
            "status": "ok",
            "message": "Event queued",
            "job_id": getattr(job, "job_id", None),
        }
    except Exception as e:
        logger.error(f"❌ Error recibiendo webhook de Yeastar: {e}")
        return JSONResponse(status_code=400, content={"error": "Invalid payload"})

def _normalize_yeastar_webhook_payload(payload: dict) -> tuple[str | None, list[str]]:
    """
    Unifica payloads legacy (action/callid) y P-Series Cloud (type + msg con call_id).
    Evento recomendado en Yeastar: 30011 Call State Changed.
    """
    return normalize_yeastar_webhook_payload(payload)
    import json as _json

    msg = payload.get("msg")
    if isinstance(msg, str):
        try:
            msg = _json.loads(msg)
        except Exception:
            msg = {}
    if not isinstance(msg, dict):
        msg = {}

    call_id = (
        payload.get("callid")
        or payload.get("call_id")
        or msg.get("call_id")
        or msg.get("callid")
    )
    if call_id is not None:
        call_id = str(call_id).strip() or None

    phones: list[str] = []
    for key in (
        "caller", "from", "src", "callernumber",
        "callee", "to", "dst", "calleenumber",
    ):
        val = payload.get(key)
        if val:
            phones.append(str(val))

    members = msg.get("members")
    if isinstance(members, str):
        try:
            members = _json.loads(members)
        except Exception:
            members = []
    if isinstance(members, list):
        for member in members:
            if not isinstance(member, dict):
                continue
            for section in ("extension", "inbound", "outbound", "internal"):
                block = member.get(section)
                if not isinstance(block, dict):
                    continue
                for key in ("from", "to", "number"):
                    val = block.get(key)
                    if val:
                        phones.append(str(val))

    return call_id, phones


async def _process_yeastar_event(payload: dict):
    """Lógica pesada de procesamiento de eventos en segundo plano."""
    await process_yeastar_webhook_payload(payload)
    return
    try:
        event_label = payload.get("action") or payload.get("type")
        call_id, phone_candidates = _normalize_yeastar_webhook_payload(payload)
        logger.info(
            f"📞 [Yeastar Background] Evento {event_label} — callid={call_id}, "
            f"teléfonos={len(phone_candidates)}"
        )

        if not call_id or not supabase:
            return

        for raw_phone in phone_candidates:
            digits = "".join(c for c in str(raw_phone) if c.isdigit())
            if len(digits) < 6:
                continue
            tail = digits[-9:] if len(digits) >= 9 else digits
            enc_res = await sb_query(
                lambda t=tail: supabase.table("encuestas")
                .select("id, datos_extra")
                .in_("status", ["initiated", "calling", "in_progress"])
                .ilike("telefono", f"%{t}%")
                .order("id", desc=True)
                .limit(1)
                .execute()
            )
            if not enc_res.data:
                continue

            row = enc_res.data[0]
            extra = row.get("datos_extra") or {}
            if isinstance(extra, str):
                try:
                    import json as _json
                    extra = _json.loads(extra)
                except Exception:
                    extra = {}
            extra["yeastar_callid"] = str(call_id)
            await sb_query(
                lambda eid=row["id"], ex=extra: supabase.table("encuestas")
                .update({"datos_extra": ex})
                .eq("id", eid)
                .execute()
            )
            logger.info(
                f"📞 [Yeastar] callid {call_id} vinculado a encuesta {row['id']} (tel ~{tail})"
            )
            break

    except Exception as e:
        logger.error(f"❌ Error en BackgroundTask de Yeastar: {e}")

# ──────────────────────────────────────────────
# Colgar sala
# ──────────────────────────────────────────────

@router.post("/colgar")
async def finalizar_llamada(req: CallEndRequest):
    """Cierra una sala de LiveKit."""
    try:
        logger.info(f"✂️ Cerrando sala: {req.nombre_sala}")
        await lkapi.room.delete_room(api.DeleteRoomRequest(room=req.nombre_sala))
        return {"status": "ok", "message": f"Sala {req.nombre_sala} cerrada"}
    except Exception as e:
        err_msg = str(e).lower()
        # Sala ya cerrada (cliente colgó primero, room_finished, etc.) → tratar como éxito
        if "not_found" in err_msg or "does not exist" in err_msg or "404" in err_msg:
            logger.info(f"✓ Sala {req.nombre_sala} ya cerrada (no existe). OK.")
            return {"status": "ok", "message": "Sala ya cerrada"}
        logger.error(f"⚠️ Error al cerrar sala {req.nombre_sala}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


# ──────────────────────────────────────────────
# Guardar encuesta y propagar a campaign_leads
# ──────────────────────────────────────────────

# Mapa canónico de estados (ES legacy + EN)
_STATUS_MAP = {
    "completed": "completed", "failed": "failed", "incomplete": "incomplete",
    "unreached": "unreached", "rejected_opt_out": "rejected_opt_out",
    "rejected": "rejected_opt_out", "calling": "calling", "pending": "pending",
    "called": "called",
    # Legacy ES
    "completada": "completed", "fallida": "failed", "parcial": "incomplete",
    "no_contesta": "failed", "rechazada": "rejected_opt_out",
    # Señales típicas SIP/telefonía que deben computar como fallida reintentable
    "busy": "failed", "ocupado": "failed",
    "voicemail": "failed", "buzon": "failed", "buzón": "failed",
}

# Estados que deben disparar la propagación a campaign_leads
_PROPAGABLE_STATUSES = {"completed", "rejected_opt_out", "incomplete", "failed", "unreached"}

# Estados terminales que no deben ser sobrescritos por el webhook de LiveKit
_TERMINAL_STATUSES = {"completed", "failed", "unreached", "incomplete", "rejected_opt_out"}


@router.post("/guardar-encuesta")
async def guardar_encuesta(datos: EncuestaData, background_tasks: BackgroundTasks):
    if not supabase:
        return {"status": "error", "message": "No DB connection"}

    logger.info(f"📥 [guardar-encuesta] encuesta={datos.id_encuesta}: {datos.dict(exclude_none=True)}")

    # --- Construir payload de actualización ---
    from typing import Any
    update_data: dict[str, Any] = {}
    if datos.nota_comercial is not None:  update_data["puntuacion_comercial"] = datos.nota_comercial
    if datos.nota_instalador is not None: update_data["puntuacion_instalador"] = datos.nota_instalador
    if datos.nota_rapidez is not None:    update_data["puntuacion_rapidez"] = datos.nota_rapidez
    if datos.comentarios is not None:     update_data["comentarios"] = datos.comentarios
    if datos.transcription is not None:   update_data["transcription"] = datos.transcription
    if datos.seconds_used is not None:    update_data["seconds_used"] = datos.seconds_used
    if datos.llm_model is not None:       update_data["llm_model"] = datos.llm_model
    if datos.datos_extra is not None:     update_data["datos_extra"] = datos.datos_extra

    # Fase 1 SaaS: si datos_extra contiene resumen_narrativo generado por call_analyzer,
    # lo persiste también en la columna dedicada encuestas.resumen_llamada para consultas
    # rápidas sin necesidad de deserializar el JSONB en cada listado.
    if isinstance(datos.datos_extra, dict):
        resumen = datos.datos_extra.get("resumen_narrativo")
        if resumen and isinstance(resumen, str) and resumen.strip():
            update_data["resumen_llamada"] = resumen.strip()[:2000]

    normalized_status = _STATUS_MAP.get((datos.status or "").strip().lower()) if datos.status else None

    if not update_data and not normalized_status:
        return {"status": "ignored", "message": "No data to update"}

    # Leer el estado actual de la encuesta en BD
    curr = await sb_query(
        lambda: supabase.table("encuestas").select("status, empresa_id, telefono").eq("id", datos.id_encuesta).execute()
    )
    curr_data = curr.data[0] if curr.data else {}
    (curr_data.get("status") or "")

    # Si llegaron datos pero sin status explícito:
    # Mantenemos el que haya calculado, si no se queda sin tocar.
    if normalized_status:
        update_data["status"] = normalized_status
        if normalized_status == "completed":
            update_data["completada"] = 1

    # --- Persistir en encuestas ---
    logger.info(f"📝 [guardar-encuesta] UPDATE encuesta {datos.id_encuesta}: {update_data}")
    try:
        await sb_query(
            lambda: supabase.table("encuestas").update(update_data).eq("id", datos.id_encuesta).execute()
        )
        logger.info(f"✅ [guardar-encuesta] Encuesta {datos.id_encuesta} actualizada")
    except Exception as e:
        logger.error(f"❌ [guardar-encuesta] Error DB: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

    # --- Propagar estado a campaign_leads ---
    if normalized_status in _PROPAGABLE_STATUSES:
        background_tasks.add_task(
            _propagate_to_lead, datos.id_encuesta, normalized_status, curr_data
        )

    # --- Notificar a n8n si el estado es terminal relevante ---
    if normalized_status in ("completed", "rejected_opt_out", "failed") and curr_data.get("empresa_id"):
        result_data = {
            "nota_comercial": datos.nota_comercial,
            "nota_instalador": datos.nota_instalador,
            "nota_rapidez": datos.nota_rapidez,
            "comentarios": datos.comentarios,
            "transcription": datos.transcription,
            "seconds_used": datos.seconds_used,
            "llm_model": datos.llm_model,
            "datos_extra": datos.datos_extra,
        }
        background_tasks.add_task(
            _notify_n8n_post_call,
            datos.id_encuesta,
            normalized_status,
            result_data,
            curr_data["empresa_id"],
            curr_data.get("telefono", ""),
        )

    return {"status": "ok", "updated": update_data}


async def _propagate_to_lead(encuesta_id: int, final_status: str, enc_curr_data: dict):
    """
    Actualiza el campaign_lead asociado a esta encuesta.
    Calcula reintentos según la configuración de la campaña.
    """
    lead_update: dict = {"status": final_status}

    if final_status == "rejected_opt_out":
        lead_update["no_reintentar"] = True

    elif final_status in ("incomplete", "failed", "unreached"):
        retry_seconds = 3600
        max_retries = 3
        current_retries = 0
        try:
            lead_res = await sb_query(
                lambda: supabase.table("campaign_leads").select("campaign_id, retries_attempted").eq("call_id", encuesta_id).limit(1).execute()
            )
            if lead_res.data:
                current_retries = lead_res.data[0].get("retries_attempted", 0) or 0
                camp_id = lead_res.data[0]["campaign_id"]
                camp_res = await sb_query(
                    lambda: supabase.table("campaigns").select("retry_interval, retries_count").eq("id", camp_id).limit(1).execute()
                )
                if camp_res.data:
                    ri = camp_res.data[0].get("retry_interval")
                    max_retries = camp_res.data[0].get("retries_count", 3) or 3
                    if ri and ri > 0:
                        retry_seconds = ri
        except Exception as e:
            logger.error(f"Error leyendo config de reintentos para encuesta {encuesta_id}: {e}")

        new_retries = current_retries + 1
        lead_update["retries_attempted"] = new_retries

        if new_retries < max_retries:
            lead_update["status"] = "pending"
            next_retry = (datetime.utcnow() + timedelta(seconds=retry_seconds)).isoformat()
            lead_update["next_retry_at"] = next_retry
            logger.info(f"🔄 Reintento {new_retries}/{max_retries} programado para encuesta {encuesta_id} → {next_retry}")
        else:
            logger.info(f"🚫 Máx. reintentos alcanzado ({new_retries}/{max_retries}) para encuesta {encuesta_id}")

    try:
        result = await sb_query(
            lambda: supabase.table("campaign_leads").update(lead_update).eq("call_id", encuesta_id).execute()
        )
        rows = len(result.data) if result.data else 0
        logger.info(f"📊 Lead actualizado (call_id={encuesta_id}): {rows} filas | {lead_update}")

        # Fallback: buscar por campaign_id + teléfono si no se encontró por call_id
        if rows == 0 and enc_curr_data.get("telefono"):
            logger.warning(f"⚠️ Fallback por teléfono para encuesta {encuesta_id}")
            enc_full = await sb_query(
                lambda: supabase.table("encuestas").select("campaign_id, telefono").eq("id", encuesta_id).execute()
            )
            if enc_full.data and enc_full.data[0].get("campaign_id"):
                camp_id = enc_full.data[0]["campaign_id"]
                tel = enc_full.data[0].get("telefono", "")
                await sb_query(
                    lambda: supabase.table("campaign_leads").update({**lead_update, "call_id": encuesta_id}).eq("campaign_id", camp_id).eq("phone_number", tel).execute()
                )
    except Exception as e:
        logger.error(f"❌ Error propagando lead para encuesta {encuesta_id}: {e}")


async def _notify_n8n_post_call(encuesta_id: int, status: str, result_data: dict, empresa_id: int, telefono: str):
    """
    Envía los datos post-llamada a:
      1. webhook_url  (Zapier / Make — payload limpio y aplanado)
      2. crm_webhook_url  (CRM específico — HubSpot / Salesforce / n8n)
      3. N8N_WEBHOOK_URL_RESULTS  (webhook global de plataforma, si existe)
    """
    try:
        emp_res = await sb_query(
            lambda: supabase.table("empresas").select("crm_webhook_url, crm_type, webhook_url").eq("id", empresa_id).execute()
        )
        emp_cfg = emp_res.data[0] if (emp_res.data) else {}
    except Exception as e:
        logger.warning(f"⚠️ No se pudo leer config de empresa {empresa_id}: {e}")
        emp_cfg = {}

    datos_extra: dict = result_data.get("datos_extra") or {}

    # ── 1. Automation webhook (Zapier / Make) ──────────────────────────────────
    automation_url = emp_cfg.get("webhook_url")
    if automation_url:
        try:
            # Payload plano: los campos de datos_extra se elevan al nivel raíz
            # para que Zapier/Make los detecte como variables individuales.
            automation_payload = {
                "event": "call.completed" if status == "completed" else (
                    "call.rejected" if status == "rejected_opt_out" else "call.failed"
                ),
                "call_id": encuesta_id,
                "phone": telefono,
                "status": status,
                "date": datetime.now(timezone.utc).isoformat(),
                "campaign_name": result_data.get("campaign_name"),
                "transcription": result_data.get("transcription"),
                "seconds_used": result_data.get("seconds_used"),
                "datos_extra": datos_extra,
                **{k: v for k, v in datos_extra.items()},  # flatten for Zapier
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(automation_url, json=automation_payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    logger.info(f"📡 Automation Webhook [{status}] → {automation_url} ({resp.status})")
        except Exception as e:
            logger.warning(f"⚠️ Error en Automation Webhook: {e}")

    # ── 2. CRM webhook (HubSpot / Salesforce / n8n) ────────────────────────────
    if emp_cfg.get("crm_webhook_url"):
        try:
            crm_payload = {
                "event": "call_completed" if status == "completed" else ("call_rejected" if status == "rejected_opt_out" else "call_failed"),
                "encuesta_id": encuesta_id,
                "empresa_id": empresa_id,
                "status": status,
                "lead": {"phone": telefono},
                "results": result_data,
                "crm_type": emp_cfg.get("crm_type", "custom"),
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(emp_cfg["crm_webhook_url"], json=crm_payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    logger.info(f"📡 CRM Webhook [{status}] → {emp_cfg['crm_webhook_url']} ({resp.status})")
        except Exception as e:
            logger.warning(f"⚠️ Error en CRM Webhook: {e}")


# ──────────────────────────────────────────────
# Llamada saliente (individual o desde campaña)
# ──────────────────────────────────────────────


@router.post("/api/telephony/test-outbound")
async def test_outbound_call(payload: TestOutboundCallRequest):
    """
    Endpoint de prueba: dispara una llamada saliente LiveKit SIP al número indicado.
    Crea sala, despacha agente y luego inicia el participante SIP.
    """
    # FIX 6: variable canónica SIP_OUTBOUND_TRUNK_ID (LIVEKIT_OUTBOUND_TRUNK_ID deprecado)
    trunk_id = await resolve_outbound_trunk_id(int(empresa_id) if str(empresa_id).isdigit() else None)
    if not trunk_id:
        raise HTTPException(
            status_code=500,
            detail="SIP_OUTBOUND_TRUNK_ID no está configurado. Define el trunk de salida en .env.",
        )

    phone = _normalize_test_outbound_phone(payload.phone_number)
    if not phone:
        raise HTTPException(status_code=400, detail="phone_number es obligatorio")

    empresa_id, survey_id, campaign_id = await _resolve_test_outbound_context(payload)
    room_name = f"llamada_ausarta_{empresa_id}_{survey_id}"

    test_contact_id = 0
    room_metadata = {
        "empresa_id": int(empresa_id),
        "survey_id": int(survey_id),
        "campaign_id": int(campaign_id),
        "campana_id": int(campaign_id),
        "contacto_id": test_contact_id,
        "client_id": test_contact_id,
        "lead_id": test_contact_id,
    }

    try:
        try:
            await create_isolated_room(room_name, metadata=room_metadata)
        except Exception as room_err:
            logger.warning(f"⚠️ [test-outbound] Aviso al crear sala {room_name}: {room_err}")

        agent_name_dispatch = (os.getenv("AGENT_NAME_DISPATCH") or "default_agent").strip()
        try:
            await dispatch_agent_explicit(
                room_name=room_name,
                agent_name=agent_name_dispatch,
                metadata=room_metadata,
            )
            agent_ready = await wait_for_agent_ready(room_name)
            if not agent_ready:
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "Agente no disponible (timeout de arranque). Revisa logs del worker LiveKit "
                        f"({agent_name_dispatch}) y que ROOM_PREFIX coincida."
                    ),
                )
        except HTTPException:
            raise
        except Exception as dispatch_err:
            logger.warning(f"⚠️ [test-outbound] Dispatch fallido: {dispatch_err}")

        sip_response = await create_outbound_call(
            number_to_dial=phone,
            trunk_id=trunk_id,
            room_name=room_name,
            empresa_id=empresa_id,
            survey_id=survey_id,
        )

        participant_id = getattr(sip_response, "participant_id", None) or getattr(
            sip_response, "participant_identity", None
        )

        return {
            "status": "ok",
            "message": "Llamada saliente iniciada",
            "room_name": room_name,
            "phone_number": phone,
            "empresa_id": int(empresa_id),
            "survey_id": int(survey_id),
            "campaign_id": int(campaign_id),
            "participant_id": participant_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [test-outbound] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# Lock para evitar doble despacho accidental
# Fallback en memoria si Redis no está disponible
_processing_rooms_fallback: set[str] = set()


async def _acquire_room_lock(room_name: str) -> bool:
    """Intenta adquirir lock distribuido para un room. Fallback a set local."""
    try:
        from services.redis_service import acquire_lock
        return await acquire_lock(f"room:{room_name}", ttl_seconds=30)
    except Exception:
        # Redis no disponible: fallback a set en memoria
        if room_name in _processing_rooms_fallback:
            return False
        _processing_rooms_fallback.add(room_name)
        return True


async def _release_room_lock(room_name: str) -> None:
    """Libera lock distribuido para un room."""
    try:
        from services.redis_service import release_lock
        await release_lock(f"room:{room_name}")
    except Exception:
        pass
    _processing_rooms_fallback.discard(room_name)


async def _check_and_increment_call_limit(empresa_id: int) -> None:
    """
    Fase 1 SaaS: verifica que la empresa no haya superado su cuota mensual
    de llamadas y, si puede llamar, incrementa el contador de forma atómica
    en Supabase usando SQL directo (RPC o UPDATE … RETURNING).

    Lanza HTTPException 403 si el límite está alcanzado.
    """
    if not supabase:
        return  # Sin BD no podemos comprobar — dejamos pasar

    try:
        emp_res = await sb_query(
            lambda: supabase.table("empresas")
            .select("plan, max_llamadas_mes, llamadas_consumidas_mes")
            .eq("id", empresa_id)
            .limit(1)
            .execute()
        )
        if not emp_res.data:
            return  # Empresa no encontrada — no bloqueamos

        emp = emp_res.data[0]
        max_calls: int = int(emp.get("max_llamadas_mes") or 100)
        used_calls: int = int(emp.get("llamadas_consumidas_mes") or 0)

        if used_calls >= max_calls:
            plan = emp.get("plan", "basico")
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Límite de llamadas mensual alcanzado para tu plan ({plan}). "
                    f"Consumidas: {used_calls}/{max_calls}. "
                    "Contacta con Ausarta para ampliar tu plan."
                ),
            )

        # Incremento atómico: evita condiciones de carrera en llamadas concurrentes.
        await sb_query(
            lambda: supabase.rpc(
                "increment_llamadas_consumidas",
                {"p_empresa_id": empresa_id},
            ).execute()
        )

    except HTTPException:
        raise
    except Exception as exc:
        # No bloqueamos la llamada si el check falla por error transitorio de BD.
        logger.warning(
            "[limits] No se pudo verificar límite de empresa %s: %s", empresa_id, exc
        )


@router.post("/api/calls/outbound")
async def make_outbound_call(request: dict, _auth: str = Depends(require_outbound_auth)):
    """Inicia una llamada SIP individual. Usado para pruebas desde el dashboard."""
    phone = request.get("phoneNumber")
    agent_id = request.get("agentId", "1")
    lead_id = request.get("leadId")
    campaign_id = request.get("campaignId")

    if not phone:
        return JSONResponse(status_code=400, content={"error": "Phone number is required"})

    encuesta_id = None

    try:
        if supabase:
            emp_id = request.get("empresa_id")
            if not emp_id and agent_id:
                try:
                    agent_res = await sb_query(
                        lambda: supabase.table("agent_config").select("empresa_id").eq("id", agent_id).execute()
                    )
                    if agent_res.data:
                        emp_id = agent_res.data[0].get("empresa_id")
                except Exception as e:
                    logger.warning(f"⚠️ [telephony] No se pudo resolver empresa desde agente {agent_id}: {e}")

            # Fase 1 SaaS: verificar cuota mensual antes de crear la encuesta/llamada.
            if emp_id:
                await _check_and_increment_call_limit(int(emp_id))

            campaign_name = request.get("campaignName")
            if campaign_id and not campaign_name:
                try:
                    camp_res = await sb_query(
                        lambda: supabase.table("campaigns").select("name").eq("id", campaign_id).execute()
                    )
                    if camp_res.data:
                        campaign_name = camp_res.data[0].get("name")
                except Exception as e:
                    logger.warning(f"⚠️ [telephony] No se pudo resolver nombre de campaña {campaign_id}: {e}")

            res_enc = await sb_query(lambda: supabase.table("encuestas").insert({
                "telefono": phone,
                "nombre_cliente": request.get("customerName", "Prueba Dashboard"),
                "fecha": datetime.now(timezone.utc).isoformat(),
                "status": "initiated",
                "completada": 0,
                "agent_id": agent_id,
                "empresa_id": emp_id,
                "campaign_id": campaign_id,
                "campaign_name": campaign_name,
            }).execute())
            encuesta_id = res_enc.data[0]["id"]

            if lead_id:
                await sb_query(
                    lambda: supabase.table("campaign_leads").update({
                        "call_id": encuesta_id,
                        "status": "calling",
                        "last_call_at": datetime.now(timezone.utc).isoformat(),
                    }).eq("id", lead_id).execute()
                )
        else:
            encuesta_id = random.randint(1000, 9999)

        agent_name_dispatch = (os.getenv("AGENT_NAME_DISPATCH") or "default_agent").strip()
        # Formato aislado estricto con prefijo de dominio propio:
        # llamada_ausarta_empresa_{id}_campana_{id}_contacto_{id}_encuesta_{id}
        contacto_id = int(lead_id) if lead_id else 0
        camp_id_str = str(campaign_id) if campaign_id else "0"
        room_name = f"llamada_ausarta_empresa_{emp_id or 0}_campana_{camp_id_str}_contacto_{contacto_id}_encuesta_{encuesta_id}"
        sip_trunk_id = await resolve_outbound_trunk_id(int(emp_id) if str(emp_id).isdigit() else None)

        # Prevención de doble despacho (lock distribuido vía Redis)
        if not await _acquire_room_lock(room_name):
            logger.warning(f"⚠️ Despacho ya en curso para {room_name}. Ignorando.")
            return {"status": "ok", "message": "Call already initiated", "roomName": room_name}

        room_metadata = {
            "empresa_id": int(emp_id or 0),
            "campaign_id": int(campaign_id or 0),
            "campana_id": int(campaign_id or 0),
            "contacto_id": contacto_id,
            "client_id": contacto_id,
            "lead_id": contacto_id,
            "survey_id": int(encuesta_id),
        }

        try:
            await create_isolated_room(room_name, metadata=room_metadata)
        except Exception as e:
            logger.warning(f"⚠️ Aviso al crear sala {room_name}: {e}")

        # Despachar agente ANTES del SIP para que esté listo cuando el cliente conteste
        try:
            await dispatch_agent_explicit(
                room_name=room_name,
                agent_name=agent_name_dispatch,
                metadata=room_metadata,
            )
            logger.info(f"✅ Agente {agent_name_dispatch} despachado a sala {room_name}")
            # FIX 1: polling real en vez de sleep fijo para evitar llamada muda
            agent_ready = await wait_for_agent_ready(room_name)
            if not agent_ready:
                logger.error(
                    f"⚠️ [outbound] Agente no listo en sala {room_name} tras timeout. "
                    "Marcando encuesta como failed y abortando SIP."
                )
                if supabase and encuesta_id:
                    try:
                        await sb_query(
                            lambda: supabase.table("encuestas")
                            .update({"status": "failed"})
                            .eq("id", encuesta_id)
                            .execute()
                        )
                    except Exception:
                        pass
                await _release_room_lock(room_name)
                return JSONResponse(
                    status_code=503,
                    content={"error": "Agente no disponible — llamada abortada para evitar audio mudo"},
                )
        except Exception as dispatch_err:
            logger.warning(f"⚠️ Dispatch explícito fallido (auto-dispatch como fallback): {dispatch_err}")

        try:
            await lkapi.sip.create_sip_participant(api.CreateSIPParticipantRequest(
                sip_trunk_id=sip_trunk_id,
                sip_call_to=phone,
                room_name=room_name,
                participant_identity=f"user_{phone}_{encuesta_id}",
                participant_name="Cliente",
            ))
        except Exception as sip_err:
            await _release_room_lock(room_name)
            raise sip_err
        except Exception as dispatch_err:
            logger.warning(f"⚠️ Dispatch explícito fallido (auto-dispatch como fallback): {dispatch_err}")

        async def clear_lock(rname: str) -> None:
            await asyncio.sleep(10)
            await _release_room_lock(rname)

        asyncio.create_task(clear_lock(room_name))

        # Grabación de audio (solo si ENABLE_RECORDING=true y credenciales configuradas)
        asyncio.create_task(_safe_start_recording(room_name, encuesta_id))

        return {"status": "ok", "roomName": room_name, "callId": encuesta_id}

    except Exception as e:
        if "room_name" in locals():
            await _release_room_lock(room_name)
        logger.error(f"❌ Error fatal en outbound call: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


# ──────────────────────────────────────────────
# Webhook de LiveKit — sustituye al polling
# ──────────────────────────────────────────────

@limiter.exempt
@router.post("/api/livekit/webhook")
async def livekit_webhook(request: Request):
    """
    Recibe eventos de LiveKit y actualiza los estados de leads y encuestas.

    Eventos relevantes:
      - room_finished: la sala se cerró (todos los participantes se fueron).
      - participant_left: un participante salió (para detectar cliente que cuelga).

    Seguridad: Valida la firma HMAC del webhook usando WebhookReceiver antes
    de procesar cualquier dato. Requests sin firma válida reciben un 401.
    """
    body_bytes = await request.body()
    auth_token = request.headers.get("Authorization", "")

    # Validar firma criptográfica antes de procesar el payload
    try:
        receiver = WebhookReceiver(_LIVEKIT_API_KEY, _LIVEKIT_API_SECRET)
        webhook_event = receiver.receive(body_bytes.decode("utf-8"), auth_token)
    except Exception as e:
        logger.warning(f"🛡️ [LK Webhook] Firma inválida o payload malformado: {e}")
        return JSONResponse(status_code=401, content={"error": "Invalid signature"})

    # Extraer campos del proto validado
    event = webhook_event.event
    room_name = webhook_event.room.name if webhook_event.HasField("room") else ""
    room_metadata_raw = webhook_event.room.metadata if webhook_event.HasField("room") else ""

    logger.info(f"🔔 [LK Webhook] Evento: {event} | Sala: {room_name}")

    if not room_name:
        return {"status": "ignored", "reason": "No room name"}

    # Parsear metadata de sala (JSON string embebido en el proto)
    room_metadata = {}
    if isinstance(room_metadata_raw, str) and room_metadata_raw.strip():
        try:
            import json
            room_metadata = json.loads(room_metadata_raw)
        except Exception:
            logger.warning(f"[LK Webhook] metadata no parseable en sala {room_name}: {room_metadata_raw}")

    encuesta_id = _extract_encuesta_id_from_room(room_name)
    if not encuesta_id:
        try:
            encuesta_id = int(room_metadata.get("survey_id") or 0)
        except Exception:
            encuesta_id = 0

    if not encuesta_id:
        logger.info(f"[LK Webhook] No se pudo extraer encuesta_id de sala {room_name} ni metadata")
        return {"status": "ignored", "reason": "No encuesta_id in room name/metadata"}

    if event == "room_finished":
        await _handle_room_finished(encuesta_id, room_name, room_metadata)

    elif event == "participant_left":
        participant_identity = webhook_event.participant.identity if webhook_event.HasField("participant") else ""
        # Solo nos interesa cuando el cliente (no el agente) se va
        if not participant_identity.startswith("agent-"):
            await _handle_participant_left(encuesta_id, room_name, participant_identity, room_metadata)

    return {"status": "ok", "event": event}


def _extract_encuesta_id_from_room(room_name: str) -> int | None:
    """
    Extrae el encuesta_id del nombre de sala. Soporta dos formatos:
      - Nuevo:   llamada_ausarta_empresa_{id}_campana_{id}_contacto_{id}_encuesta_{encuesta_id}
      - Intermedio: empresa_{id}_camp_{id}_call_{encuesta_id}
      - Legacy:  {prefix}_encuesta_{encuesta_id}  o  encuesta_{encuesta_id}
    Retorna None si no se puede extraer.
    """
    try:
        # Formato nuevo estricto: ..._encuesta_{id}
        if "encuesta_" in room_name:
            after_enc = room_name.split("encuesta_")[-1]
            candidate = after_enc.split("_")[0]
            if candidate.isdigit():
                return int(candidate)

        # Formato intermedio: empresa_N_camp_N_call_N
        if "call_" in room_name:
            after_call = room_name.split("call_")[-1]
            candidate = after_call.split("_")[0]
            if candidate.isdigit():
                return int(candidate)

        # Fallback: el último segmento numérico
        parts = room_name.split("_")
        for segment in reversed(parts):
            if segment.isdigit():
                return int(segment)

        return None
    except Exception:
        return None



async def _safe_start_recording(room_name: str, encuesta_id: int) -> None:
    """Inicia la grabación de audio sin bloquear el flujo principal."""
    try:
        from services.recording_service import start_recording
        await start_recording(room_name, encuesta_id)
    except Exception as exc:
        logger.debug(f"[Recording] start_recording ignorado: {exc}")


async def _safe_stop_recording(encuesta_id: int) -> None:
    """Para la grabación y guarda la URL en la encuesta si existe."""
    try:
        from services.recording_service import stop_recording
        recording_url = await stop_recording(encuesta_id)
        if recording_url and supabase:
            await asyncio.to_thread(
                supabase.table("encuestas")
                    .update({"recording_url": recording_url})
                    .eq("id", encuesta_id)
                    .execute
            )
            logger.info(f"🎵 [Recording] URL guardada para encuesta {encuesta_id}: {recording_url}")
    except Exception as exc:
        logger.debug(f"[Recording] stop_recording ignorado: {exc}")


async def _handle_room_finished(encuesta_id: int, room_name: str, room_metadata: dict | None = None):
    """
    La sala se cerró. Si el estado en BD todavía no es terminal,
    significa que la llamada no se completó normalmente → marcamos 'failed'.

    Si la encuesta tiene transcripción, encola el análisis con LLM vía ARQ
    (process_transcription_ai) en lugar de llamar a n8n.
    """
    if not supabase:
        return

    # Parar grabación (si estaba activa) antes de cualquier otra cosa
    asyncio.create_task(_safe_stop_recording(encuesta_id))

    try:
        res = await asyncio.to_thread(
            supabase.table("encuestas")
                .select("status, empresa_id, telefono, transcription")
                .eq("id", encuesta_id)
                .limit(1)
                .execute
        )
        if not res.data:
            return

        enc = res.data[0]
        current_status = enc.get("status") or ""

        if current_status not in _TERMINAL_STATUSES:
            # La sala cerró pero el agente no guardó un status final → fallida reintentable
            logger.warning(f"📵 [LK Webhook] Sala {room_name} cerrada sin status terminal. Forzando 'failed'. metadata={room_metadata or {}}")
            await asyncio.to_thread(
                supabase.table("encuestas").update({"status": "failed"}).eq("id", encuesta_id).execute
            )
            # Propagar a campaign_leads
            await _propagate_to_lead(encuesta_id, "failed", enc)
        else:
            logger.info(f"[LK Webhook] Sala {room_name} cerrada con status terminal: {current_status}. Sin acción.")

        # Encolar análisis de transcripción vía ARQ (reemplaza llamada HTTP a n8n)
        transcription = enc.get("transcription") or ""
        empresa_id = enc.get("empresa_id")
        if transcription.strip() and empresa_id:
            try:
                from services.queue_service import get_arq_pool
                arq_pool = await get_arq_pool()
                job = await arq_pool.enqueue_job(
                    "process_transcription_ai",
                    encuesta_id,
                    transcription,
                    empresa_id,
                )
                logger.info(
                    f"📬 [LK Webhook] Tarea process_transcription_ai encolada para "
                    f"encuesta {encuesta_id} (job_id={getattr(job, 'job_id', 'n/a')})."
                )
            except Exception as eq:
                # No bloquear el flujo principal si la cola falla
                logger.warning(f"⚠️ [LK Webhook] No se pudo encolar transcripción para encuesta {encuesta_id}: {eq}")
        else:
            logger.info(f"[LK Webhook] Encuesta {encuesta_id} sin transcripción o empresa_id. Skipping análisis AI.")

    except Exception as e:
        logger.error(f"❌ [LK Webhook] Error en room_finished para encuesta {encuesta_id}: {e}")


async def _handle_participant_left(encuesta_id: int, room_name: str, identity: str, room_metadata: dict | None = None):
    """
    Un participante (cliente) salió de la sala.
    No hacemos nada terminante aquí: esperamos el evento room_finished.
    Solo registramos el evento para auditoría.
    """
    logger.info(f"👤 [LK Webhook] Participante '{identity}' salió de sala {room_name} (encuesta {encuesta_id}, metadata={room_metadata or {}}). Esperando room_finished.")


# ─────────────────────────────────────────────────────────────────────────────
# EXTENSIONES YEASTAR — CRUD por empresa
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/empresas/{empresa_id}/extensions")
async def list_extensions(
    empresa_id: int,
    current_user: CurrentUser = Depends(get_current_user),
):
    """Lista las extensiones Yeastar configuradas para una empresa."""
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión con la base de datos")

    is_global = has_global_access(current_user)
    if not is_global and str(current_user.empresa_id) != str(empresa_id):
        raise HTTPException(status_code=403, detail="Acceso denegado")

    res = await sb_query(
        lambda eid=empresa_id: supabase.table("yeastar_extensions")
        .select("id, extension_number, extension_name, departamento, created_at, updated_at")
        .eq("empresa_id", eid)
        .order("extension_number")
        .execute()
    )
    return res.data or []


@router.post("/api/empresas/{empresa_id}/extensions/sync")
async def sync_yeastar_extensions(
    empresa_id: int,
    current_user: CurrentUser = Depends(require_admin),
):
    """Sincroniza extensiones desde Yeastar P-Series hacia la tabla local."""
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexiÃ³n con la base de datos")

    if not has_global_access(current_user) and str(current_user.empresa_id) != str(empresa_id):
        raise HTTPException(status_code=403, detail="Acceso denegado")

    config = await _load_yeastar_tenant_config(empresa_id)
    async with _yeastar_client_from_config(config) as client:
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
    return {
        "status": "ok",
        "synced": len(rows),
        "extensions": res.data or [],
    }


@router.get("/api/empresas/{empresa_id}/extensions/statuses")
async def get_yeastar_extension_statuses(
    empresa_id: int,
    current_user: CurrentUser = Depends(require_admin),
):
    """Consulta estado real en Yeastar para las extensiones locales."""
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexiÃ³n con la base de datos")

    if not has_global_access(current_user) and str(current_user.empresa_id) != str(empresa_id):
        raise HTTPException(status_code=403, detail="Acceso denegado")

    ext_res = await sb_query(
        lambda eid=empresa_id: supabase.table("yeastar_extensions")
        .select("extension_number")
        .eq("empresa_id", eid)
        .order("extension_number")
        .execute()
    )
    extensions = [str(row.get("extension_number")) for row in (ext_res.data or []) if row.get("extension_number")]
    config = await _load_yeastar_tenant_config(empresa_id)

    statuses: dict[str, str] = {}
    async with _yeastar_client_from_config(config) as client:
        for extension in extensions:
            statuses[extension] = await client.get_extension_status(extension)

    return {"statuses": statuses}


@router.post("/api/empresas/{empresa_id}/extensions", status_code=201)
async def create_extension(
    empresa_id: int,
    payload: dict,
    current_user: CurrentUser = Depends(require_admin),
):
    """Crea una nueva extensión Yeastar para una empresa."""
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión con la base de datos")

    is_global = has_global_access(current_user)
    if not is_global and str(current_user.empresa_id) != str(empresa_id):
        raise HTTPException(status_code=403, detail="Acceso denegado")

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


@router.put("/api/empresas/{empresa_id}/extensions/{ext_id}")
async def update_extension(
    empresa_id: int,
    ext_id: str,
    payload: dict,
    current_user: CurrentUser = Depends(require_admin),
):
    """Actualiza una extensión Yeastar existente."""
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión con la base de datos")

    is_global = has_global_access(current_user)
    if not is_global and str(current_user.empresa_id) != str(empresa_id):
        raise HTTPException(status_code=403, detail="Acceso denegado")

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


@router.delete("/api/empresas/{empresa_id}/extensions/{ext_id}", status_code=204)
async def delete_extension(
    empresa_id: int,
    ext_id: str,
    current_user: CurrentUser = Depends(require_admin),
):
    """Elimina una extensión Yeastar."""
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión con la base de datos")

    is_global = has_global_access(current_user)
    if not is_global and str(current_user.empresa_id) != str(empresa_id):
        raise HTTPException(status_code=403, detail="Acceso denegado")

    await sb_query(
        lambda eid=empresa_id, eid2=ext_id: supabase.table("yeastar_extensions")
        .delete()
        .eq("empresa_id", eid)
        .eq("id", eid2)
        .execute()
    )
    return


# ─────────────────────────────────────────────────────────────────────────────
# COLGAR LLAMADA — Endpoint para panel de monitorización en vivo
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/api/calls/hang_up")
async def hang_up_call(
    payload: dict,
    current_user: CurrentUser = Depends(require_admin),
):
    """
    Cierra/cuelga una sala LiveKit activa.
    Body: { "room_name": str }
    """
    room_name = (payload.get("room_name") or "").strip()
    if not room_name:
        raise HTTPException(status_code=400, detail="room_name es obligatorio")

    try:
        from services.queue_service import get_arq_pool
        arq_pool = await get_arq_pool()
        job = await arq_pool.enqueue_job("colgar_sala", room_name)
        logger.info(f"📬 [hang_up] Colgar sala {room_name} encolado (job={getattr(job, 'job_id', 'n/a')})")
    except Exception as q_err:
        logger.warning(f"⚠️ [hang_up] No se pudo encolar colgar sala {room_name}: {q_err}")
        if lkapi:
            try:
                from livekit import api as lk_api
                await lkapi.room.delete_room(lk_api.DeleteRoomRequest(room=room_name))
                logger.info(f"✅ [hang_up] Sala {room_name} cerrada directamente via LiveKit API")
            except Exception as lk_err:
                raise HTTPException(status_code=502, detail=f"Error cerrando sala: {lk_err}") from lk_err

    return {"status": "ok", "room_name": room_name, "message": "Sala cerrada"}
