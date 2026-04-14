"""
yeastar_service.py — Cliente async para la API REST de centralitas Yeastar.

Compatibilidad:
  - Yeastar S-Series (S20 / S50 / S100 / S300)  — API v1.0
  - Yeastar P-Series (P550 / P570 / P620 / P660) — API v1.0 (misma estructura)

Flujo de autenticación:
  1. POST /api/v1.0/get_token  → devuelve {"status":"Success","token":"<tok>","refreshtoken":"<rt>"}
  2. Todas las peticiones siguientes llevan el token en la query-string (?token=<tok>)
     o bien en el header X-Authorization (según versión del firmware).

Referencia: https://help.yeastar.com/en/s-series/topic/api_overview.html
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any

import aiohttp

logger = logging.getLogger("api-backend")

# Timeout for every Yeastar API call (seconds)
_TIMEOUT = aiohttp.ClientTimeout(total=10)


@dataclass
class YeastarTokenBundle:
    token: str
    refresh_token: str | None = None


class YeastarConnectionError(Exception):
    """Raised when the Yeastar API is unreachable or returns an error."""


class YeastarAuthError(YeastarConnectionError):
    """Raised when credentials are invalid."""


class YeastarClient:
    """
    Stateless async client for the Yeastar REST API.

    Usage (one-shot test):
        client = YeastarClient(api_url="192.168.1.100", api_port=8088,
                               username="admin", password="secret")
        ok, message = await client.test_connection()

    Usage (real calls):
        bundle = await client.login()
        data   = await client.get("/api/v1.0/pbx/extensions/list", bundle.token)
    """

    def __init__(
        self,
        api_url: str,
        api_port: int,
        username: str,
        password: str,
        *,
        use_https: bool = False,
    ) -> None:
        scheme = "https" if use_https else "http"
        # Normalise url — strip trailing slashes and any existing scheme
        host = api_url.strip().rstrip("/").removeprefix("https://").removeprefix("http://")
        self.base_url = f"{scheme}://{host}:{api_port}"
        self.username = username
        self._password = password
        self._session: aiohttp.ClientSession | None = None

    def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=_TIMEOUT)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    # ──────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _md5(value: str) -> str:
        """Yeastar expects the password as its MD5 digest (hex, lowercase)."""
        return hashlib.md5(value.encode()).hexdigest()

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Low-level async POST, returns parsed JSON or raises."""
        url = f"{self.base_url}{path}"
        session = self.get_session()
        try:
            async with session.post(url, json=payload, ssl=False) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise YeastarConnectionError(
                        f"HTTP {resp.status} from {url}: {text[:200]}"
                    )
                return await resp.json(content_type=None)
        except aiohttp.ClientConnectorError as exc:
            raise YeastarConnectionError(
                f"No se puede conectar a {self.base_url}: {exc}"
            ) from exc
        except aiohttp.ServerTimeoutError as exc:
            raise YeastarConnectionError(
                f"Timeout conectando a {self.base_url}"
            ) from exc

    async def _get(self, path: str, token: str) -> dict[str, Any]:
        """Low-level async GET with token in query-string."""
        url = f"{self.base_url}{path}"
        session = self.get_session()
        try:
            async with session.get(
                url, params={"token": token}, ssl=False
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise YeastarConnectionError(
                        f"HTTP {resp.status} from {url}: {text[:200]}"
                    )
                return await resp.json(content_type=None)
        except aiohttp.ClientConnectorError as exc:
            raise YeastarConnectionError(
                f"No se puede conectar a {self.base_url}: {exc}"
            ) from exc

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────

    async def login(self) -> YeastarTokenBundle:
        """
        Authenticate against the Yeastar API.
        Returns a YeastarTokenBundle with the session token.

        Yeastar accepts the password as plain-text OR as MD5 depending on
        firmware version. We try MD5 first (most common); if the API rejects
        it with an auth error we retry with plain-text.
        """
        for password_value in (self._md5(self._password), self._password):
            try:
                data = await self._post(
                    "/api/v1.0/get_token",
                    {"username": self.username, "password": password_value},
                )
            except YeastarConnectionError:
                raise

            status = data.get("status", "")
            if status == "Success":
                return YeastarTokenBundle(
                    token=data["token"],
                    refresh_token=data.get("refreshtoken"),
                )

            err_code = data.get("errno", "") or data.get("errcode", "")
            # 10011 = invalid credentials; try next password variant
            if str(err_code) not in ("10011", "Invalid password"):
                raise YeastarAuthError(
                    f"Error de autenticación Yeastar (errno={err_code}): {data}"
                )

        raise YeastarAuthError(
            "Credenciales inválidas — revisa usuario y contraseña de la API."
        )

    async def get_system_info(self, token: str) -> dict[str, Any]:
        """Fetch basic PBX system info as a lightweight connectivity check."""
        return await self._get("/api/v1.0/pbx/system/info", token)

    async def test_connection(self) -> tuple[bool, str]:
        """
        Full round-trip test:
          1. Login → get token
          2. Fetch /pbx/system/info with that token

        Returns:
            (True, success_message) on success.
            (False, error_message) on failure.
        """
        try:
            bundle = await self.login()
            info = await self.get_system_info(bundle.token)

            firmware = info.get("firmware", info.get("version", "desconocida"))
            model = info.get("model", "Yeastar PBX")
            return True, (
                f"Conexión exitosa con {model} "
                f"(firmware: {firmware}) en {self.base_url}"
            )

        except YeastarAuthError as exc:
            logger.warning(f"[Yeastar] Auth error: {exc}")
            return False, str(exc)

        except YeastarConnectionError as exc:
            logger.warning(f"[Yeastar] Connection error: {exc}")
            return False, str(exc)

        except Exception as exc:
            logger.error(f"[Yeastar] Unexpected error during test: {exc}")
            return False, f"Error inesperado: {exc}"
