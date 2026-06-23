"""Validación de URLs externas (protección SSRF)."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

_BLOCKED_NETWORKS = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)

_BLOCKED_HOSTNAMES = frozenset({"localhost", "localhost.localdomain"})


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return any(ip in network for network in _BLOCKED_NETWORKS)


def _parse_and_precheck(url: str) -> str | None:
    """
    Valida el esquema y el hostname literal.
    Devuelve el hostname si hay que resolver DNS, o None si ya se puede
    responder sin resolución (bloqueado o URL inválida levanta False implícita).
    Lanza ValueError si la URL debe ser rechazada de inmediato.
    """
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https"):
        raise ValueError("scheme")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("no_hostname")

    hostname_lower = hostname.lower().strip(".")
    if hostname_lower in _BLOCKED_HOSTNAMES:
        raise ValueError("blocked_hostname")

    # Si es una IP literal, verificar sin DNS
    try:
        literal = ipaddress.ip_address(hostname_lower)
        if _is_blocked_ip(literal):
            raise ValueError("blocked_ip_literal")
        # Es una IP pública: no necesita resolución DNS
        return None
    except (ValueError, ipaddress.AddressValueError):
        pass  # Es un hostname: necesita resolución DNS

    return hostname_lower


def is_safe_external_url(url: str) -> bool:
    """
    True si la URL es http(s) pública y no resuelve a rangos privados/reservados.

    NOTA: usa socket.getaddrinfo() síncrono — solo llamar desde contextos
    síncronos (tests, scripts). En endpoints FastAPI/async usar
    is_safe_external_url_async() para no bloquear el event loop.
    """
    try:
        hostname = _parse_and_precheck(url)
    except ValueError:
        return False

    if hostname is None:
        return True  # IP literal pública, ya validada

    try:
        for family, _, _, _, sockaddr in socket.getaddrinfo(hostname, None):
            if family not in (socket.AF_INET, socket.AF_INET6):
                continue
            ip = ipaddress.ip_address(sockaddr[0])
            if _is_blocked_ip(ip):
                return False
    except OSError:
        return False

    return True


async def is_safe_external_url_async(url: str) -> bool:
    """
    Versión async de is_safe_external_url — no bloquea el event loop.

    Usar en todos los endpoints FastAPI. La resolución DNS se delega a
    asyncio mediante loop.getaddrinfo(), que ejecuta en el thread pool
    del executor sin congelar el loop.
    """
    try:
        hostname = _parse_and_precheck(url)
    except ValueError:
        return False

    if hostname is None:
        return True  # IP literal pública, ya validada

    try:
        loop = asyncio.get_event_loop()
        results = await loop.getaddrinfo(hostname, None)
        for family, _, _, _, sockaddr in results:
            if family not in (socket.AF_INET, socket.AF_INET6):
                continue
            ip = ipaddress.ip_address(sockaddr[0])
            if _is_blocked_ip(ip):
                return False
    except OSError:
        return False

    return True
