"""
yeastar_service.py — Cliente async para la API REST de centralitas Yeastar P-Series.

Flujo de autenticación (OAuth2 Client Credentials):
  1. POST /api/v2.0/token  → devuelve access_token temporal.
  2. Todas las peticiones llevan el token en el header Authorization: Bearer <tok>.

El token se cachea en Redis (TTL 3500s) para compartirlo entre workers Gunicorn/Uvicorn.
"""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

from services.redis_service import cache_get, cache_set

logger = logging.getLogger("api-backend")

_TIMEOUT = aiohttp.ClientTimeout(total=10)
_TOKEN_TTL_SECONDS = 3500


class YeastarConnectionError(Exception):
    """Raised when the Yeastar API is unreachable or returns an error."""


class YeastarAuthError(YeastarConnectionError):
    """Raised when credentials are invalid."""


def _token_cache_key(pbx_url: str, client_id: str) -> str:
    return f"yeastar:token:{pbx_url}:{client_id}"


class YeastarPSeriesClient:
    """
    Async client for the Yeastar P-Series REST API (v2.0).
    """

    def __init__(
        self,
        pbx_url: str,
        client_id: str,
        client_secret: str,
        *,
        tenant_id: int | str | None = None,
    ) -> None:
        host = pbx_url.strip().rstrip("/")
        if not host.startswith("http"):
            host = f"https://{host}"
        self.base_url = host
        self.client_id = client_id
        self.client_secret = client_secret
        self.tenant_id = tenant_id
        self._session: aiohttp.ClientSession | None = None

    @property
    def tenant_label(self) -> str:
        """Identificador legible para logs (PBX + tenant opcional)."""
        if self.tenant_id is not None:
            return f"tenant={self.tenant_id} pbx={self.base_url}"
        return f"pbx={self.base_url}"

    def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=_TIMEOUT)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def _post(self, path: str, payload: dict[str, Any], token: str | None = None) -> dict[str, Any]:
        """Low-level async POST."""
        url = f"{self.base_url}{path}"
        session = self.get_session()
        headers: dict[str, str] = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        try:
            async with session.post(url, json=payload, headers=headers, ssl=False) as resp:
                if resp.status not in (200, 201):
                    text = await resp.text()
                    raise YeastarConnectionError(
                        f"[{self.tenant_label}] HTTP {resp.status} from {url}: {text[:200]}"
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

    async def _get(self, path: str, token: str) -> dict[str, Any]:
        """Low-level async GET."""
        url = f"{self.base_url}{path}"
        session = self.get_session()
        headers = {"Authorization": f"Bearer {token}"}
        try:
            async with session.get(url, headers=headers, ssl=False) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise YeastarConnectionError(
                        f"[{self.tenant_label}] HTTP {resp.status} from {url}: {text[:200]}"
                    )
                return await resp.json(content_type=None)
        except aiohttp.ClientConnectorError as exc:
            raise YeastarConnectionError(
                f"[{self.tenant_label}] No se puede conectar a {self.base_url}: {exc}"
            ) from exc

    async def get_access_token(self) -> str:
        """
        Fetch or retrieve cached token using client_credentials (Redis, TTL 3500s).
        """
        cache_key = _token_cache_key(self.base_url, self.client_id)
        try:
            cached = await cache_get(cache_key)
            if cached:
                return cached
        except Exception as cache_err:
            logger.warning(
                f"[Yeastar] [{self.tenant_label}] Caché Redis no disponible, solicitando token nuevo: {cache_err}"
            )

        payload = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

        try:
            data = await self._post("/api/v2.0/token", payload)

            if data.get("errcode") != 0 and "access_token" not in data:
                raise YeastarAuthError(
                    f"[{self.tenant_label}] Error de autenticación Yeastar: {data}"
                )

            token = data["access_token"]

            try:
                await cache_set(cache_key, token, _TOKEN_TTL_SECONDS)
            except Exception as cache_err:
                logger.warning(
                    f"[Yeastar] [{self.tenant_label}] No se pudo guardar token en Redis: {cache_err}"
                )

            return token

        except YeastarConnectionError as e:
            raise YeastarAuthError(
                f"[{self.tenant_label}] Fallo al conectar para auth: {e}"
            ) from e

    async def test_connection(self) -> tuple[bool, str]:
        """Test connection and auth."""
        try:
            token = await self.get_access_token()
            data = await self._get("/api/v2.0/extension/list", token)

            if data.get("errcode") == 0:
                return True, "Conexión exitosa y autenticación correcta con la PBX."
            return False, f"Autenticado, pero error al listar: {data}"

        except YeastarAuthError as exc:
            logger.warning(f"[Yeastar] [{self.tenant_label}] Auth error: {exc}")
            return False, str(exc)
        except Exception as exc:
            logger.error(f"[Yeastar] [{self.tenant_label}] Unexpected error during test: {exc}")
            return False, f"Error inesperado: {exc}"

    async def transfer_call(self, call_id: str, target_extension: str) -> dict:
        """
        Transfer an ongoing call to a target extension.
        """
        try:
            token = await self.get_access_token()
            payload = {
                "callid": call_id,
                "transfer_to": target_extension,
            }

            logger.info(
                f"[Yeastar] [{self.tenant_label}] Transfiriendo llamada {call_id} → ext {target_extension}"
            )
            response = await self._post("/api/v2.0/pbx/call/transfer", payload, token=token)

            if response.get("errcode") != 0:
                logger.error(
                    f"[Yeastar] [{self.tenant_label}] Error al transferir llamada {call_id}: {response}"
                )
                raise YeastarConnectionError(
                    f"[{self.tenant_label}] Error al transferir: {response}"
                )

            return response

        except YeastarConnectionError:
            raise
        except Exception as e:
            logger.error(
                f"[Yeastar] [{self.tenant_label}] Excepción durante transfer_call "
                f"(call_id={call_id}, ext={target_extension}): {e}"
            )
            raise
