"""
api_credits.py — Consulta saldos / consumo de los proveedores externos.

Diseñado para el panel de administrador (Dashboard → "Créditos de APIs").
Solo accesible para usuarios con rol admin o superadmin (Depends(require_admin)).

Cada proveedor expone (o no) un endpoint público para consultar saldo:

| Proveedor   | API de saldo                                              | Notas                                |
|-------------|-----------------------------------------------------------|--------------------------------------|
| Deepgram    | GET /v1/projects → /v1/projects/{id}/balances             | Devuelve saldo en USD                |
| OpenAI      | GET /dashboard/billing/credit_grants (legacy)             | Solo claves de cuenta antigua; nuevo |
|             | GET /v1/organization/usage (Admin Key)                    | requiere Admin Key                   |
| Cartesia    | No expone saldo público                                   | Solo ping al voices endpoint         |
| ElevenLabs  | GET /v1/user/subscription                                 | character_count / character_limit    |
| Twilio      | GET /2010-04-01/Accounts/{Sid}/Balance.json               | Basic auth                           |
| Groq        | No expone saldo                                           | -                                    |
| Google      | No expone saldo (Gemini)                                  | -                                    |
| LiveKit     | Self-hosted                                               | -                                    |
| Supabase    | Sin API pública de billing por proyecto                   | -                                    |

El endpoint hace best-effort: si una API responde con error o no soporta consulta
de saldo, devuelve `supported=False` con una nota explicativa y un enlace al
dashboard del proveedor.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import aiohttp
from fastapi import APIRouter, Depends

from services.auth import CurrentUser, require_admin

logger = logging.getLogger("api-backend")

router = APIRouter(prefix="/api/admin", tags=["api-credits"])

_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=8)


def _entry(
    provider: str,
    *,
    key_configured: bool,
    supported: bool,
    status: str = "ok",
    balance: Optional[float] = None,
    balance_unit: Optional[str] = None,
    usage_amount: Optional[float] = None,
    usage_limit: Optional[float] = None,
    usage_unit: Optional[str] = None,
    period: Optional[str] = None,
    note: Optional[str] = None,
    dashboard_url: Optional[str] = None,
) -> dict[str, Any]:
    return {
        "provider": provider,
        "key_configured": key_configured,
        "supported": supported,
        "status": status,
        "balance": balance,
        "balance_unit": balance_unit,
        "usage_amount": usage_amount,
        "usage_limit": usage_limit,
        "usage_unit": usage_unit,
        "period": period,
        "note": note,
        "dashboard_url": dashboard_url,
    }


async def _check_deepgram(session: aiohttp.ClientSession) -> dict[str, Any]:
    key = os.getenv("DEEPGRAM_API_KEY")
    if not key:
        return _entry(
            "Deepgram",
            key_configured=False,
            supported=True,
            status="no_key",
            note="DEEPGRAM_API_KEY no configurada.",
            dashboard_url="https://console.deepgram.com/billing",
        )

    headers = {"Authorization": f"Token {key}"}
    try:
        async with session.get(
            "https://api.deepgram.com/v1/projects", headers=headers
        ) as r:
            if r.status == 401:
                return _entry(
                    "Deepgram",
                    key_configured=True,
                    supported=True,
                    status="auth_error",
                    note="API key inválida (401).",
                    dashboard_url="https://console.deepgram.com/billing",
                )
            r.raise_for_status()
            data = await r.json()
        projects = data.get("projects") or []
        if not projects:
            return _entry(
                "Deepgram",
                key_configured=True,
                supported=True,
                status="no_data",
                note="La cuenta no tiene proyectos.",
                dashboard_url="https://console.deepgram.com/billing",
            )
        proj_id = projects[0].get("project_id")
        async with session.get(
            f"https://api.deepgram.com/v1/projects/{proj_id}/balances",
            headers=headers,
        ) as r:
            r.raise_for_status()
            balances = (await r.json()).get("balances") or []
        if not balances:
            return _entry(
                "Deepgram",
                key_configured=True,
                supported=True,
                status="no_data",
                note="Sin saldo registrado.",
                dashboard_url="https://console.deepgram.com/billing",
            )
        b = balances[0]
        amount = float(b.get("amount") or 0)
        unit = b.get("units") or "USD"
        return _entry(
            "Deepgram",
            key_configured=True,
            supported=True,
            balance=round(amount, 2),
            balance_unit=unit,
            note="Saldo restante (prepago).",
            dashboard_url="https://console.deepgram.com/billing",
        )
    except aiohttp.ClientResponseError as e:
        logger.warning("Deepgram balance error: %s", e)
        return _entry(
            "Deepgram",
            key_configured=True,
            supported=True,
            status="error",
            note=f"HTTP {e.status}",
            dashboard_url="https://console.deepgram.com/billing",
        )
    except Exception as e:
        logger.warning("Deepgram balance exception: %s", e)
        return _entry(
            "Deepgram",
            key_configured=True,
            supported=True,
            status="error",
            note=str(e)[:120],
            dashboard_url="https://console.deepgram.com/billing",
        )


async def _check_openai(session: aiohttp.ClientSession) -> dict[str, Any]:
    key = os.getenv("OPENAI_API_KEY")
    admin_key = os.getenv("OPENAI_ADMIN_KEY")
    if not key and not admin_key:
        return _entry(
            "OpenAI",
            key_configured=False,
            supported=True,
            status="no_key",
            dashboard_url="https://platform.openai.com/usage",
        )

    # 1) Si hay Admin Key: API oficial de costes del mes actual.
    if admin_key:
        try:
            now = datetime.now(timezone.utc)
            start = int(datetime(now.year, now.month, 1, tzinfo=timezone.utc).timestamp())
            url = f"https://api.openai.com/v1/organization/costs?start_time={start}&bucket_width=1d"
            async with session.get(
                url, headers={"Authorization": f"Bearer {admin_key}"}
            ) as r:
                if r.ok:
                    data = await r.json()
                    total = 0.0
                    for bucket in data.get("data", []) or []:
                        for res in bucket.get("results", []) or []:
                            amt = (res.get("amount") or {}).get("value")
                            if amt is not None:
                                total += float(amt)
                    return _entry(
                        "OpenAI",
                        key_configured=True,
                        supported=True,
                        usage_amount=round(total, 2),
                        usage_unit="USD",
                        period=f"{now.strftime('%Y-%m')} (mes en curso)",
                        note="Gasto del mes en curso (Admin Key).",
                        dashboard_url="https://platform.openai.com/usage",
                    )
        except Exception as e:
            logger.debug("OpenAI admin costs error: %s", e)

    # 2) Sin Admin Key no hay forma pública de leer saldo con sk- normal.
    return _entry(
        "OpenAI",
        key_configured=True,
        supported=False,
        status="no_api",
        note="OpenAI no expone créditos con claves sk-. Define OPENAI_ADMIN_KEY para ver el gasto del mes.",
        dashboard_url="https://platform.openai.com/usage",
    )


async def _check_elevenlabs(session: aiohttp.ClientSession) -> dict[str, Any]:
    key = os.getenv("ELEVENLABS_API_KEY") or os.getenv("XI_API_KEY")
    if not key:
        return _entry(
            "ElevenLabs",
            key_configured=False,
            supported=True,
            status="no_key",
            dashboard_url="https://elevenlabs.io/app/subscription",
        )
    try:
        async with session.get(
            "https://api.elevenlabs.io/v1/user/subscription",
            headers={"xi-api-key": key},
        ) as r:
            r.raise_for_status()
            data = await r.json()
        used = int(data.get("character_count") or 0)
        limit = int(data.get("character_limit") or 0)
        return _entry(
            "ElevenLabs",
            key_configured=True,
            supported=True,
            usage_amount=used,
            usage_limit=limit,
            usage_unit="caracteres",
            period=data.get("next_character_count_reset_unix")
            and "Cuota mensual"
            or None,
            note=f"Tier {data.get('tier') or 'free'}.",
            dashboard_url="https://elevenlabs.io/app/subscription",
        )
    except Exception as e:
        logger.debug("ElevenLabs balance error: %s", e)
        return _entry(
            "ElevenLabs",
            key_configured=True,
            supported=True,
            status="error",
            note=str(e)[:120],
            dashboard_url="https://elevenlabs.io/app/subscription",
        )


async def _check_twilio(session: aiohttp.ClientSession) -> Optional[dict[str, Any]]:
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    if not sid or not token:
        return None
    try:
        async with session.get(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Balance.json",
            auth=aiohttp.BasicAuth(sid, token),
        ) as r:
            r.raise_for_status()
            data = await r.json()
        return _entry(
            "Twilio",
            key_configured=True,
            supported=True,
            balance=round(float(data.get("balance") or 0), 2),
            balance_unit=data.get("currency") or "USD",
            note="Saldo de la cuenta.",
            dashboard_url="https://console.twilio.com/us1/billing",
        )
    except Exception as e:
        logger.debug("Twilio balance error: %s", e)
        return _entry(
            "Twilio",
            key_configured=True,
            supported=True,
            status="error",
            note=str(e)[:120],
            dashboard_url="https://console.twilio.com/us1/billing",
        )


async def _check_cartesia(session: aiohttp.ClientSession) -> dict[str, Any]:
    key = os.getenv("CARTESIA_API_KEY")
    if not key:
        return _entry(
            "Cartesia",
            key_configured=False,
            supported=False,
            status="no_key",
            dashboard_url="https://play.cartesia.ai/console",
        )
    # Cartesia no expone API pública de saldo. Comprobamos solo que la clave es válida.
    try:
        async with session.get(
            "https://api.cartesia.ai/voices",
            headers={"X-API-Key": key, "Cartesia-Version": "2024-06-10"},
        ) as r:
            if r.status == 401:
                return _entry(
                    "Cartesia",
                    key_configured=True,
                    supported=False,
                    status="auth_error",
                    note="API key inválida (401).",
                    dashboard_url="https://play.cartesia.ai/console",
                )
    except Exception:
        pass
    return _entry(
        "Cartesia",
        key_configured=True,
        supported=False,
        status="no_api",
        note="Cartesia no expone API pública de saldo. Revisa el panel.",
        dashboard_url="https://play.cartesia.ai/console",
    )


def _stub(
    provider: str,
    env_key: str,
    dashboard_url: str,
    note: str,
) -> dict[str, Any]:
    return _entry(
        provider,
        key_configured=bool(os.getenv(env_key)),
        supported=False,
        status="no_api",
        note=note,
        dashboard_url=dashboard_url,
    )


@router.get("/api-credits")
async def get_api_credits(
    _user: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    """
    Devuelve el saldo / consumo conocido por proveedor.

    Estructura:
    {
      "last_checked": "ISO-8601",
      "providers": [
        {provider, key_configured, supported, status, balance, balance_unit,
         usage_amount, usage_limit, usage_unit, period, note, dashboard_url},
        ...
      ]
    }

    `supported=False` significa que el proveedor no expone API de saldo;
    se incluye `dashboard_url` para que el admin lo consulte manualmente.
    """
    async with aiohttp.ClientSession(timeout=_HTTP_TIMEOUT) as session:
        tasks = await asyncio.gather(
            _check_deepgram(session),
            _check_openai(session),
            _check_cartesia(session),
            _check_elevenlabs(session),
            _check_twilio(session),
            return_exceptions=True,
        )

    providers: list[dict[str, Any]] = []
    for t in tasks:
        if isinstance(t, Exception):
            logger.warning("api-credits provider check raised: %s", t)
            continue
        if t is None:
            continue
        providers.append(t)

    providers.extend([
        _stub(
            "Groq",
            "GROQ_API_KEY",
            "https://console.groq.com/settings/billing",
            "Groq no expone API pública de saldo.",
        ),
        _stub(
            "Google Gemini",
            "GOOGLE_API_KEY",
            "https://aistudio.google.com/app/usage",
            "Google AI no expone API pública de saldo.",
        ),
        _stub(
            "LiveKit",
            "LIVEKIT_API_KEY",
            "https://cloud.livekit.io/projects",
            "Servidor LiveKit auto-hospedado (sin coste por API).",
        ),
    ])

    providers.sort(
        key=lambda p: (
            0 if (p["supported"] and p["key_configured"]) else 1,
            0 if p["key_configured"] else 1,
            p["provider"].lower(),
        )
    )

    try:
        from services.api_credits_alerts import maybe_alert_low_balances

        await maybe_alert_low_balances(providers)
    except Exception as exc:
        logger.debug("api-credits alerts omitidas: %s", exc)

    return {
        "last_checked": datetime.now(timezone.utc).isoformat(),
        "providers": providers,
    }
