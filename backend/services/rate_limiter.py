"""
rate_limiter.py — Instancia compartida de slowapi Limiter.

Definida aquí (y no en api.py) para que los routers puedan
importarla sin crear dependencias circulares.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])
