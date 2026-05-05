"""
yeastar_service.py — Cliente async para la API REST de centralitas Yeastar P-Series.

Flujo de autenticación (OAuth2 Client Credentials):
  1. POST /api/v2.0/token  → devuelve access_token temporal.
  2. Todas las peticiones llevan el token en la query-string (?access_token=<tok>)
     o bien en el header Authorization: Bearer <tok>.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
import asyncio
import time

import aiohttp

logger = logging.getLogger("api-backend")

_TIMEOUT = aiohttp.ClientTimeout(total=10)

class YeastarConnectionError(Exception):
    """Raised when the Yeastar API is unreachable or returns an error."""

class YeastarAuthError(YeastarConnectionError):
    """Raised when credentials are invalid."""

# Simple token cache to avoid requesting a token on every call
_TOKEN_CACHE = {}

class YeastarPSeriesClient:
    """
    Async client for the Yeastar P-Series REST API (v2.0).
    """

    def __init__(
        self,
        pbx_url: str,
        client_id: str,
        client_secret: str,
    ) -> None:
        # Normalise url
        host = pbx_url.strip().rstrip("/")
        if not host.startswith("http"):
            host = f"https://{host}"
        self.base_url = host
        self.client_id = client_id
        self.client_secret = client_secret
        self._session: aiohttp.ClientSession | None = None

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
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
            
        try:
            async with session.post(url, json=payload, headers=headers, ssl=False) as resp:
                if resp.status not in (200, 201):
                    text = await resp.text()
                    raise YeastarConnectionError(
                        f"HTTP {resp.status} from {url}: {text[:200]}"
                    )
                return await resp.json(content_type=None)
        except aiohttp.ClientConnectorError as exc:
            raise YeastarConnectionError(f"No se puede conectar a {self.base_url}: {exc}") from exc
        except aiohttp.ServerTimeoutError as exc:
            raise YeastarConnectionError(f"Timeout conectando a {self.base_url}") from exc

    async def _get(self, path: str, token: str) -> dict[str, Any]:
        """Low-level async GET."""
        url = f"{self.base_url}{path}"
        session = self.get_session()
        headers = {"Authorization": f"Bearer {token}"}
        try:
            async with session.get(url, headers=headers, ssl=False) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise YeastarConnectionError(f"HTTP {resp.status} from {url}: {text[:200]}")
                return await resp.json(content_type=None)
        except aiohttp.ClientConnectorError as exc:
            raise YeastarConnectionError(f"No se puede conectar a {self.base_url}: {exc}") from exc

    async def get_access_token(self) -> str:
        """
        Fetch or retrieve cached token using client_credentials.
        """
        cache_key = f"{self.base_url}_{self.client_id}"
        cached = _TOKEN_CACHE.get(cache_key)
        
        # Check if we have a valid token (leave 60s margin)
        if cached and cached['expires_at'] > time.time() + 60:
            return cached['token']

        payload = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret
        }
        
        try:
            data = await self._post("/api/v2.0/token", payload)
            
            if data.get("errcode") != 0 and "access_token" not in data:
                raise YeastarAuthError(f"Error de autenticación Yeastar: {data}")
                
            token = data["access_token"]
            expires_in = data.get("expires_in", 3600)
            
            _TOKEN_CACHE[cache_key] = {
                "token": token,
                "expires_at": time.time() + expires_in
            }
            return token
            
        except YeastarConnectionError as e:
            raise YeastarAuthError(f"Fallo al conectar para auth: {e}")

    async def test_connection(self) -> tuple[bool, str]:
        """Test connection and auth."""
        try:
            token = await self.get_access_token()
            # Try a simple GET to verify the token works, like getting extensions
            data = await self._get("/api/v2.0/extension/list", token)
            
            if data.get("errcode") == 0:
                return True, "Conexión exitosa y autenticación correcta con la PBX."
            else:
                return False, f"Autenticado, pero error al listar: {data}"
                
        except YeastarAuthError as exc:
            logger.warning(f"[Yeastar] Auth error: {exc}")
            return False, str(exc)
        except Exception as exc:
            logger.error(f"[Yeastar] Unexpected error during test: {exc}")
            return False, f"Error inesperado: {exc}"

    async def transfer_call(self, call_id: str, target_extension: str) -> dict:
        """
        Transfer an ongoing call to a target extension.
        """
        try:
            token = await self.get_access_token()
            payload = {
                "callid": call_id,
                "transfer_to": target_extension
            }
            
            logger.info(f"Yeastar: Transfiriendo llamada {call_id} a ext {target_extension}")
            response = await self._post("/api/v2.0/pbx/call/transfer", payload, token=token)
            
            if response.get("errcode") != 0:
                logger.error(f"Yeastar: Error al transferir llamada: {response}")
                raise YeastarConnectionError(f"Error al transferir: {response}")
                
            return response
            
        except Exception as e:
            logger.error(f"Yeastar: Excepción durante transfer_call: {e}")
            raise
