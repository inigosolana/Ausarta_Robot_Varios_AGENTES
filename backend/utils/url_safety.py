"""Validación de URLs externas (protección SSRF)."""

from __future__ import annotations

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


def is_safe_external_url(url: str) -> bool:
    """
    True si la URL es http(s) pública y no resuelve a rangos privados/reservados.
  """
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https"):
        return False

    hostname = parsed.hostname
    if not hostname:
        return False

    hostname_lower = hostname.lower().strip(".")
    if hostname_lower in _BLOCKED_HOSTNAMES:
        return False

    try:
        literal = ipaddress.ip_address(hostname_lower)
        return not _is_blocked_ip(literal)
    except ValueError:
        pass

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
