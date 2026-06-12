import asyncio
import logging
import os

import aiohttp

logger = logging.getLogger("api-backend")


async def send_telegram_alert(message: str, parse_mode: str = "HTML") -> bool:
    """Envía mensaje al bot/canal configurado en TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID."""
    bot_token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()

    if not bot_token or not chat_id:
        logger.debug("[telegram] TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID no configurados — omitiendo envío.")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": parse_mode}

    try:
        async with aiohttp.ClientSession() as session:
            response = await asyncio.wait_for(
                session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=5)),
                timeout=5,
            )
            async with response:
                if response.status >= 400:
                    body = await response.text()
                    logger.warning(
                        "⚠️ [telegram] Error enviando alerta HTTP %s: %s",
                        response.status,
                        body[:200],
                    )
                    return False
        logger.info("✅ [telegram] Alerta enviada.")
        return True
    except Exception as exc:
        logger.warning("⚠️ [telegram] No se pudo enviar alerta: %s", exc)
        return False
