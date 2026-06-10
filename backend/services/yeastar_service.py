"""
Async client for Yeastar APIs.

Supported modes:
  - pseries: P-Series OpenAPI on /openapi/v1.0
  - cloud_pbx: legacy Cloud PBX login/token flow on /api/v2.0.0
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Literal
from urllib.parse import urlencode

import aiohttp

from services.redis_service import cache_delete, cache_get, cache_set

logger = logging.getLogger("api-backend")

YeastarApiMode = Literal["pseries", "cloud_pbx"]

_TIMEOUT = aiohttp.ClientTimeout(total=12)
_TOKEN_TTL_SECONDS = 3500


class YeastarConnectionError(Exception):
    """Raised when the Yeastar API is unreachable or returns an error."""


class YeastarAuthError(YeastarConnectionError):
    """Raised when credentials are invalid."""


def _token_cache_key(base_url: str, api_mode: YeastarApiMode, client_id: str) -> str:
    return f"yeastar:token:{api_mode}:{base_url}:{client_id}"


def _normalize_base_url(pbx_url: str) -> str:
    host = pbx_url.strip().rstrip("/")
    if not host.startswith("http"):
        host = f"https://{host}"
    return host


def _format_yeastar_error(data: Any, *, api_mode: YeastarApiMode) -> str:
    if not isinstance(data, dict):
        return str(data)

    invalid_items = data.get("invalid_param_list")
    route_error = ""
    if isinstance(invalid_items, list):
        for item in invalid_items:
            if isinstance(item, dict) and "No route for" in str(item.get("value") or ""):
                route_error = str(item.get("value") or "")
                break

    if data.get("errcode") == 10001 and route_error:
        mode_label = "Cloud PBX" if api_mode == "cloud_pbx" else "P-Series"
        return (
            f"La URL base responde, pero no expone la API Yeastar {mode_label} "
            f"en ese endpoint ({route_error}). Revisa que la API este habilitada "
            "y que estes usando el dominio/puerto API real de la centralita."
        )

    if data.get("status") == "Failed" and data.get("errno"):
        return f"Autenticacion Yeastar fallida (errno={data.get('errno')})."

    return str(data)


class YeastarClient:
    """Async client for Yeastar P-Series and Cloud PBX APIs."""

    def __init__(
        self,
        pbx_url: str,
        client_id: str,
        client_secret: str,
        *,
        api_mode: YeastarApiMode = "pseries",
        tenant_id: int | str | None = None,
    ) -> None:
        self.base_url = _normalize_base_url(pbx_url)
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()
        self.api_mode = api_mode
        self.tenant_id = tenant_id
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> "YeastarClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    @property
    def tenant_label(self) -> str:
        if self.tenant_id is not None:
            return f"tenant={self.tenant_id} mode={self.api_mode} pbx={self.base_url}"
        return f"mode={self.api_mode} pbx={self.base_url}"

    def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=_TIMEOUT,
                headers={"User-Agent": "OpenAPI"},
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_payload: dict[str, Any] | None = None,
        token: str | None = None,
        auth_header: bool = False,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers: dict[str, str] = {}
        if token and auth_header:
            headers["Authorization"] = f"Bearer {token}"

        session = self.get_session()
        try:
            async with session.request(
                method,
                url,
                json=json_payload,
                headers=headers,
                ssl=False,
            ) as resp:
                if resp.status not in (200, 201):
                    text = await resp.text()
                    raise YeastarConnectionError(
                        f"[{self.tenant_label}] HTTP {resp.status} from {url}: {text[:250]}"
                    )
                return await resp.json(content_type=None)
        except aiohttp.ClientConnectorError as exc:
            raise YeastarConnectionError(
                f"[{self.tenant_label}] No se puede conectar a {self.base_url}: {exc}"
            ) from exc
        except aiohttp.ServerTimeoutError as exc:
            raise YeastarConnectionError(
                f"[{self.tenant_label}] Timeout conectando a {self.base_url}"
            ) from exc

    async def _pseries_request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        token: str | None = None,
    ) -> dict[str, Any]:
        query = f"?{urlencode({'access_token': token})}" if token else ""
        return await self._request(method, f"/openapi/v1.0/{path}{query}", json_payload=payload)

    async def _cloud_request(
        self,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        token: str | None = None,
    ) -> dict[str, Any]:
        query = f"?{urlencode({'token': token})}" if token else ""
        return await self._request("POST", f"/api/v2.0.0/{path}{query}", json_payload=payload)

    async def get_access_token(self, *, force_refresh: bool = False) -> str:
        cache_key = _token_cache_key(self.base_url, self.api_mode, self.client_id)
        tenant_id = int(self.tenant_id) if self.tenant_id is not None else None
        if force_refresh:
            try:
                await cache_delete(cache_key, empresa_id=tenant_id)
            except Exception as cache_err:
                logger.warning("[Yeastar] [%s] No se pudo invalidar token: %s", self.tenant_label, cache_err)
        else:
            try:
                cached = await cache_get(cache_key, empresa_id=tenant_id)
                if cached:
                    return cached
            except Exception as cache_err:
                logger.warning("[Yeastar] [%s] Cache no disponible: %s", self.tenant_label, cache_err)

        try:
            if self.api_mode == "cloud_pbx":
                secret_md5 = hashlib.md5(self.client_secret.encode("utf-8")).hexdigest()
                data = await self._request(
                    "POST",
                    "/api/v2.0.0/login",
                    json_payload={
                        "username": self.client_id,
                        "password": secret_md5,
                        "version": "2.0.0",
                    },
                )
                if str(data.get("status") or "").lower() != "success" or not data.get("token"):
                    raise YeastarAuthError(
                        f"[{self.tenant_label}] {_format_yeastar_error(data, api_mode=self.api_mode)}"
                    )
                token = str(data["token"])
            else:
                data = await self._pseries_request(
                    "POST",
                    "get_token",
                    payload={
                        "username": self.client_id,
                        "password": self.client_secret,
                    },
                )
                if data.get("errcode") not in (None, 0) or "access_token" not in data:
                    raise YeastarAuthError(
                        f"[{self.tenant_label}] {_format_yeastar_error(data, api_mode=self.api_mode)}"
                    )
                token = str(data["access_token"])

            try:
                await cache_set(
                    cache_key,
                    token,
                    _TOKEN_TTL_SECONDS,
                    empresa_id=tenant_id,
                )
            except Exception as cache_err:
                logger.warning("[Yeastar] [%s] No se pudo cachear token: %s", self.tenant_label, cache_err)

            return token
        except YeastarConnectionError as exc:
            raise YeastarAuthError(f"[{self.tenant_label}] Fallo al conectar para auth: {exc}") from exc

    @staticmethod
    def _token_expired(response: dict[str, Any]) -> bool:
        return response.get("errcode") == 10004 or str(response.get("errmsg") or "").upper() == "TOKEN EXPIRED"

    async def _authenticated_pseries_request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        token = await self.get_access_token()
        response = await self._pseries_request(method, path, payload=payload, token=token)
        if self._token_expired(response):
            token = await self.get_access_token(force_refresh=True)
            response = await self._pseries_request(method, path, payload=payload, token=token)
        return response

    async def test_connection(self) -> tuple[bool, str]:
        try:
            extensions = await self.list_extensions()
            mode_label = "Yeastar Cloud PBX" if self.api_mode == "cloud_pbx" else "Yeastar P-Series"
            return True, f"Conexion correcta con {mode_label}. Extensiones visibles: {len(extensions)}."
        except YeastarAuthError as exc:
            logger.warning("[Yeastar] [%s] Auth error: %s", self.tenant_label, exc)
            return False, str(exc)
        except Exception as exc:
            logger.error("[Yeastar] [%s] Error inesperado en test: %s", self.tenant_label, exc)
            return False, f"Error inesperado: {exc}"

    async def list_trunks(self) -> list[dict[str, Any]]:
        if self.api_mode == "cloud_pbx":
            token = await self.get_access_token()
            response = await self._cloud_request("trunk/list", token=token)
            if str(response.get("status") or "").lower() != "success":
                raise YeastarConnectionError(
                    f"[{self.tenant_label}] {_format_yeastar_error(response, api_mode=self.api_mode)}"
                )
            data = response.get("trunklist") or []
        else:
            response = await self._authenticated_pseries_request("GET", "trunk/list")
            if response.get("errcode") not in (None, 0):
                raise YeastarConnectionError(
                    f"[{self.tenant_label}] {_format_yeastar_error(response, api_mode=self.api_mode)}"
                )
            data = response.get("data") or response.get("trunks") or []
            if isinstance(data, dict):
                data = data.get("trunks") or data.get("list") or data.get("items") or []

        trunks: list[dict[str, Any]] = []
        for item in data or []:
            if not isinstance(item, dict):
                continue
            trunk_id = item.get("id") or item.get("trunk_id") or item.get("name") or item.get("trunkname") or ""
            trunks.append({
                "provider": "yeastar",
                "id": str(trunk_id),
                "name": item.get("name") or item.get("trunk_name") or item.get("trunkname") or str(trunk_id),
                "phone_numbers": item.get("numbers") or item.get("did_numbers") or item.get("dids") or (
                    [item.get("def_outbound_cid")] if item.get("def_outbound_cid") else []
                ),
                "status": item.get("status") or item.get("state") or "configured",
                "type": item.get("type") or item.get("trunk_type"),
                "address": item.get("host_port") or item.get("host") or item.get("address"),
                "raw": item,
            })
        return trunks

    async def list_extensions(self) -> list[dict[str, Any]]:
        if self.api_mode == "cloud_pbx":
            token = await self.get_access_token()
            response = await self._cloud_request("extension/list", token=token)
            if str(response.get("status") or "").lower() != "success":
                raise YeastarConnectionError(
                    f"[{self.tenant_label}] {_format_yeastar_error(response, api_mode=self.api_mode)}"
                )
            data = response.get("extlist") or []
        else:
            response = await self._authenticated_pseries_request("GET", "extension/list")
            if response.get("errcode") not in (None, 0):
                raise YeastarConnectionError(
                    f"[{self.tenant_label}] {_format_yeastar_error(response, api_mode=self.api_mode)}"
                )
            data = response.get("data") or response.get("extensions") or []
            if isinstance(data, dict):
                data = data.get("extensions") or data.get("list") or data.get("items") or []

        extensions: list[dict[str, Any]] = []
        for item in data or []:
            if not isinstance(item, dict):
                continue
            number = (
                item.get("number")
                or item.get("extension")
                or item.get("extension_number")
                or item.get("ext_number")
                or item.get("extnumber")
                or item.get("id")
            )
            if number is None:
                continue
            extensions.append({
                "extension_number": str(number),
                "extension_name": item.get("name") or item.get("caller_id_name") or item.get("display_name") or item.get("username"),
                "departamento": item.get("department") or item.get("department_name"),
                "status": item.get("status") or item.get("presence") or item.get("state"),
                "raw": item,
            })
        return extensions

    async def get_extension_status(self, extension: str) -> str:
        try:
            extensions = await self.list_extensions()
            for item in extensions:
                if str(item.get("extension_number")) == str(extension):
                    return str(item.get("status") or "Unknown")
            return "Unregistered"
        except Exception as exc:
            logger.warning("[Yeastar] [%s] get_extension_status(%s): %s", self.tenant_label, extension, exc)
            return "Error"

    async def transfer_call(self, channel_id: str, target_extension: str) -> dict[str, Any]:
        try:
            if self.api_mode == "cloud_pbx":
                token = await self.get_access_token()
                response = await self._cloud_request(
                    "call/transfer",
                    token=token,
                    payload={
                        "channelid": channel_id,
                        "number": target_extension,
                    },
                )
                if str(response.get("status") or "").lower() != "success":
                    raise YeastarConnectionError(
                        f"[{self.tenant_label}] Transferencia Cloud fallida. "
                        f"Cloud PBX suele requerir channelid del evento 30011: {response}"
                    )
                return response

            response = await self._authenticated_pseries_request(
                "POST",
                "call/transfer",
                payload={
                    "type": "blind",
                    "channel_id": channel_id,
                    "number": target_extension,
                },
            )
            if response.get("errcode") != 0:
                raise YeastarConnectionError(
                    f"[{self.tenant_label}] Error al transferir: {response}"
                )
            return response
        except YeastarConnectionError:
            raise
        except Exception as exc:
            logger.error(
                "[Yeastar] [%s] Excepcion durante transfer_call (channel_id=%s, ext=%s): %s",
                self.tenant_label,
                channel_id,
                target_extension,
                exc,
            )
            raise


    async def create_sip_trunk(
        self,
        trunk_name: str,
        host: str,
        port: int = 5060,
        transport: str = "udp",
        ddi: str | None = None,
    ) -> dict[str, Any]:
        """
        Crea (o reutiliza) una troncal SIP peer_did en el Yeastar del cliente
        apuntando al servidor SIP de LiveKit.

        Usa type=peer_did con country=XX (sin plantilla ITSP específica → equivale
        a "General" en la UI, lo que permite activar la troncal sin restricciones
        de plan).  La troncal se activa automáticamente al crearse.

        - errcode 70103: hostname ya ocupado → buscamos la troncal existente por host y la reutilizamos.
        - Solo soportado en modo pseries.
        """
        if self.api_mode == "cloud_pbx":
            logger.warning(
                "[Yeastar] [%s] create_sip_trunk no soportado en cloud_pbx — omitiendo",
                self.tenant_label,
            )
            return {"skipped": True, "reason": "cloud_pbx_not_supported"}

        host_port = f"{host}:{port}"

        # did_list obligatorio para peer_did; si no hay DDI usamos placeholder
        did_entry = ddi.strip() if ddi else "+000000000"
        payload: dict[str, Any] = {
            "name": trunk_name,
            "type": "peer_did",
            "hostname": host,
            "port": port,
            "domain": host,
            "transport": transport.lower(),
            # XX = código de país inexistente → Yeastar aplica plantilla "General"
            # (evita la plantilla ES que deja la troncal desactivada en planes cloud)
            "country": "XX",
            "codec_sel": "ulaw",
            "did_list": [{"did": did_entry}],
        }
        response = await self._authenticated_pseries_request(
            "POST",
            "trunk/create",
            payload=payload,
        )

        # errcode 70103 → hostname:port ya usado por otra troncal → la reutilizamos
        if response.get("errcode") == 70103:
            trunks = await self.list_trunks()
            existing = next(
                (t for t in trunks if str(t.get("address", "")).startswith(host)),
                None,
            )
            if existing:
                logger.info(
                    "[Yeastar] [%s] Host %s:%d ya está en troncal '%s' — reutilizando",
                    self.tenant_label, host, port, existing["name"],
                )
                return {"skipped": False, "name": existing["name"], "reused": True, "id": existing["id"]}
            raise YeastarConnectionError(
                f"[{self.tenant_label}] Host {host_port} ya ocupado pero no se encontró la troncal: {response}"
            )

        # errcode 40003 → nombre duplicado → la troncal ya existe con ese nombre
        if response.get("errcode") == 40003:
            logger.info(
                "[Yeastar] [%s] Troncal SIP '%s' ya existe — reutilizando",
                self.tenant_label,
                trunk_name,
            )
            return {"skipped": False, "name": trunk_name, "reused": True}

        if response.get("errcode") not in (None, 0):
            raise YeastarConnectionError(
                f"[{self.tenant_label}] Error creando troncal SIP '{trunk_name}': {response}"
            )

        trunk_id = response.get("id")

        # Activar la troncal tras crearla (hostname + port = campos permitidos en update)
        try:
            await self._authenticated_pseries_request(
                "POST",
                "trunk/update",
                payload={"id": trunk_id, "hostname": host, "port": port, "domain": host},
            )
        except Exception as exc:
            logger.warning("[Yeastar] [%s] No se pudo hacer update post-creación: %s", self.tenant_label, exc)

        logger.info(
            "[Yeastar] [%s] Troncal SIP '%s' creada OK (host=%s:%d, id=%s)",
            self.tenant_label, trunk_name, host, port, trunk_id,
        )
        return {**response, "name": trunk_name, "host_port": host_port, "reused": False}

    async def create_inbound_route(
        self,
        ddi: str,
        trunk_name: str,
    ) -> dict[str, Any]:
        """
        Crea ruta entrante en Yeastar: DDI del cliente → troncal SIP hacia LiveKit.
        Si ya existe una ruta con ese nombre, la sobreescribe.
        Solo soportado en modo pseries (P-Series OpenAPI).
        """
        route_name = f"ausarta_{ddi.replace('+', '').replace(' ', '')}"
        if self.api_mode == "cloud_pbx":
            logger.warning(
                "[Yeastar] [%s] create_inbound_route no soportado en cloud_pbx — omitiendo",
                self.tenant_label,
            )
            return {"skipped": True, "reason": "cloud_pbx_not_supported"}

        response = await self._authenticated_pseries_request(
            "POST",
            "inbound_route/create",
            payload={
                "name": route_name,
                "did_number": ddi,
                "trunk": trunk_name,
                "destination_type": "trunk",
            },
        )
        # errcode 110011 = ya existe → hacer update en su lugar
        if response.get("errcode") == 110011:
            logger.info(
                "[Yeastar] [%s] Ruta '%s' ya existe — actualizando",
                self.tenant_label,
                route_name,
            )
            response = await self._authenticated_pseries_request(
                "POST",
                "inbound_route/update",
                payload={
                    "name": route_name,
                    "did_number": ddi,
                    "trunk": trunk_name,
                    "destination_type": "trunk",
                },
            )
        if response.get("errcode") not in (None, 0):
            raise YeastarConnectionError(
                f"[{self.tenant_label}] Error creando ruta entrante DDI={ddi}: {response}"
            )
        logger.info(
            "[Yeastar] [%s] Ruta entrante '%s' creada/actualizada OK (DDI=%s → trunk=%s)",
            self.tenant_label,
            route_name,
            ddi,
            trunk_name,
        )
        return response

    async def configure_event_push(self, webhook_url: str) -> dict[str, Any]:
        """
        Configura Event Push en Yeastar para que envíe eventos de llamada
        al webhook de Ausarta (/webhooks/yeastar).
        Activa el evento 30011 (Call State Changed), que es el que ya procesa el backend.
        Solo soportado en modo pseries.
        """
        if self.api_mode == "cloud_pbx":
            logger.warning(
                "[Yeastar] [%s] configure_event_push no soportado en cloud_pbx — omitiendo",
                self.tenant_label,
            )
            return {"skipped": True, "reason": "cloud_pbx_not_supported"}

        response = await self._authenticated_pseries_request(
            "POST",
            "advanced_setting/event_push",
            payload={
                "enable": True,
                "url": webhook_url,
                "events": ["30011"],
                "method": "POST",
                "content_type": "application/json",
            },
        )
        if response.get("errcode") not in (None, 0):
            raise YeastarConnectionError(
                f"[{self.tenant_label}] Error configurando event push → {webhook_url}: {response}"
            )
        logger.info(
            "[Yeastar] [%s] Event Push configurado OK → %s",
            self.tenant_label,
            webhook_url,
        )
        return response


YeastarPSeriesClient = YeastarClient
