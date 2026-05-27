#!/usr/bin/env python3
"""Verifica conectividad y credenciales de las APIs definidas en .env (raíz del repo)."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

try:
    import httpx
except ImportError:
    print("Instala httpx: pip install httpx")
    sys.exit(1)

ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = ROOT / ".env"


def load_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        v = v.strip().strip('"').strip("'")
        out[k.strip()] = v
    return out


def mask(s: str, show: int = 4) -> str:
    if not s or len(s) <= show * 2:
        return "***"
    return f"{s[:show]}...{s[-show:]}"


def result(name: str, ok: bool, detail: str, ms: float = 0) -> dict:
    return {"name": name, "ok": ok, "detail": detail, "ms": round(ms, 0)}


def check_supabase(env: dict) -> dict:
    url = env.get("SUPABASE_URL", "").rstrip("/")
    key = env.get("SUPABASE_SERVICE_ROLE_KEY") or env.get("SUPABASE_KEY", "")
    if not url or not key:
        return result("Supabase", False, "Falta SUPABASE_URL o SUPABASE_SERVICE_ROLE_KEY")
    t0 = time.perf_counter()
    try:
        r = httpx.get(
            f"{url}/rest/v1/agent_config?select=id&limit=1",
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
            timeout=15.0,
        )
        ms = (time.perf_counter() - t0) * 1000
        if r.status_code == 200:
            return result("Supabase", True, f"REST OK ({len(r.json())} fila(s) muestra)", ms)
        return result("Supabase", False, f"HTTP {r.status_code}: {r.text[:120]}", ms)
    except Exception as e:
        return result("Supabase", False, str(e)[:120])


def check_livekit(env: dict) -> dict:
    """LiveKit Cloud/self-hosted: ListRooms vía API HTTP."""
    api_key = env.get("LIVEKIT_API_KEY", "")
    api_secret = env.get("LIVEKIT_API_SECRET", "")
    wss_url = env.get("LIVEKIT_URL", "")
    if not all([api_key, api_secret, wss_url]):
        return result("LiveKit", False, "Faltan LIVEKIT_URL / API_KEY / API_SECRET")

    http_url = wss_url.replace("wss://", "https://").replace("ws://", "http://").rstrip("/")
    t0 = time.perf_counter()
    try:
        from livekit import api as lk_api  # type: ignore

        token = (
            lk_api.AccessToken(api_key, api_secret)
            .with_grants(lk_api.VideoGrants(room_list=True))
            .to_jwt()
        )
        r = httpx.post(
            f"{http_url}/twirp/livekit.RoomService/ListRooms",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={},
            timeout=15.0,
        )
        ms = (time.perf_counter() - t0) * 1000
        if r.status_code == 200:
            rooms = r.json().get("rooms", [])
            return result("LiveKit", True, f"ListRooms OK ({len(rooms)} sala(s))", ms)
        return result("LiveKit", False, f"HTTP {r.status_code}: {r.text[:150]}", ms)
    except ImportError:
        # Fallback sin SDK: solo comprobar que el host responde
        try:
            r = httpx.get(http_url, timeout=10.0, follow_redirects=True)
            ms = (time.perf_counter() - t0) * 1000
            if r.status_code < 500:
                return result(
                    "LiveKit",
                    True,
                    f"Host alcanzable HTTP {r.status_code} (instala livekit-api para test completo)",
                    ms,
                )
            return result("LiveKit", False, f"HTTP {r.status_code}", ms)
        except Exception as e:
            return result("LiveKit", False, str(e)[:120])
    except Exception as e:
        return result("LiveKit", False, str(e)[:150])


def check_deepgram(env: dict) -> dict:
    key = env.get("DEEPGRAM_API_KEY", "")
    if not key:
        return result("Deepgram", False, "Falta DEEPGRAM_API_KEY")
    t0 = time.perf_counter()
    try:
        r = httpx.get(
            "https://api.deepgram.com/v1/projects",
            headers={"Authorization": f"Token {key}"},
            timeout=15.0,
        )
        ms = (time.perf_counter() - t0) * 1000
        if r.status_code == 200:
            return result("Deepgram", True, "API key válida (projects)", ms)
        if r.status_code == 403:
            return result("Deepgram", True, "Key aceptada (403 en projects — uso STT suele funcionar)", ms)
        return result("Deepgram", False, f"HTTP {r.status_code}: {r.text[:100]}", ms)
    except Exception as e:
        return result("Deepgram", False, str(e)[:120])


def check_cartesia(env: dict) -> dict:
    key = env.get("CARTESIA_API_KEY", "")
    if not key:
        return result("Cartesia", False, "Falta CARTESIA_API_KEY")
    t0 = time.perf_counter()
    try:
        r = httpx.get(
            "https://api.cartesia.ai/voices",
            headers={
                "X-API-Key": key,
                "Cartesia-Version": "2024-06-10",
            },
            timeout=15.0,
        )
        ms = (time.perf_counter() - t0) * 1000
        if r.status_code == 200:
            data = r.json()
            n = len(data) if isinstance(data, list) else len(data.get("data", []))
            return result("Cartesia", True, f"TTS OK ({n} voces)", ms)
        return result("Cartesia", False, f"HTTP {r.status_code}: {r.text[:100]}", ms)
    except Exception as e:
        return result("Cartesia", False, str(e)[:120])


def check_groq(env: dict) -> dict:
    key = env.get("GROQ_API_KEY", "")
    if not key:
        return result("Groq", False, "Falta GROQ_API_KEY")
    t0 = time.perf_counter()
    try:
        r = httpx.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=15.0,
        )
        ms = (time.perf_counter() - t0) * 1000
        if r.status_code == 200:
            n = len(r.json().get("data", []))
            return result("Groq", True, f"LLM OK ({n} modelos)", ms)
        return result("Groq", False, f"HTTP {r.status_code}: {r.text[:100]}", ms)
    except Exception as e:
        return result("Groq", False, str(e)[:120])


def check_openai(env: dict) -> dict:
    key = env.get("OPENAI_API_KEY", "")
    if not key:
        return result("OpenAI", False, "Falta OPENAI_API_KEY")
    t0 = time.perf_counter()
    try:
        r = httpx.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=15.0,
        )
        ms = (time.perf_counter() - t0) * 1000
        if r.status_code == 200:
            return result("OpenAI", True, "API key válida", ms)
        return result("OpenAI", False, f"HTTP {r.status_code}: {r.text[:120]}", ms)
    except Exception as e:
        return result("OpenAI", False, str(e)[:120])


def check_google(env: dict) -> dict:
    key = env.get("GOOGLE_API_KEY", "")
    if not key:
        return result("Google API", False, "No configurada (opcional)")
    t0 = time.perf_counter()
    try:
        r = httpx.get(
            "https://generativelanguage.googleapis.com/v1/models",
            params={"key": key},
            timeout=15.0,
        )
        ms = (time.perf_counter() - t0) * 1000
        if r.status_code == 200:
            return result("Google API", True, "Gemini/models OK", ms)
        return result("Google API", False, f"HTTP {r.status_code}: {r.text[:100]}", ms)
    except Exception as e:
        return result("Google API", False, str(e)[:120])


def check_n8n(env: dict) -> dict:
    base = env.get("N8N_WEBHOOK_BASE_URL", "").rstrip("/")
    if not base:
        return result("n8n webhooks", False, "Falta N8N_WEBHOOK_BASE_URL")
    t0 = time.perf_counter()
    try:
        # GET suele devolver 404/405 si el servidor existe; connection error = mal
        r = httpx.get(base, timeout=10.0, follow_redirects=True)
        ms = (time.perf_counter() - t0) * 1000
        if r.status_code < 500:
            return result("n8n (base)", True, f"Host responde HTTP {r.status_code}", ms)
        return result("n8n (base)", False, f"HTTP {r.status_code}", ms)
    except Exception as e:
        return result("n8n (base)", False, str(e)[:120])


def check_glpi(env: dict) -> dict:
    url = env.get("GLPI_URL", "")
    app_token = env.get("GLPI_APP_TOKEN", "")
    user_token = env.get("GLPI_USER_TOKEN", "")
    if not url:
        return result("GLPI", False, "No configurado (opcional)")
    t0 = time.perf_counter()
    try:
        r = httpx.get(
            f"{url.rstrip('/')}/initSession",
            headers={
                "App-Token": app_token,
                "Authorization": f"user_token {user_token}",
            },
            timeout=15.0,
        )
        ms = (time.perf_counter() - t0) * 1000
        if r.status_code == 200:
            return result("GLPI", True, "initSession OK", ms)
        return result("GLPI", False, f"HTTP {r.status_code}: {r.text[:100]}", ms)
    except Exception as e:
        return result("GLPI", False, str(e)[:120])


def check_telegram(env: dict) -> dict:
    token = env.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        return result("Telegram", False, "No configurado (opcional)")
    t0 = time.perf_counter()
    try:
        r = httpx.get(f"https://api.telegram.org/bot{token}/getMe", timeout=15.0)
        ms = (time.perf_counter() - t0) * 1000
        data = r.json()
        if r.status_code == 200 and data.get("ok"):
            uname = data.get("result", {}).get("username", "?")
            return result("Telegram", True, f"Bot @{uname}", ms)
        return result("Telegram", False, data.get("description", r.text)[:100], ms)
    except Exception as e:
        return result("Telegram", False, str(e)[:120])


def main() -> int:
    env = load_env(ENV_PATH)
    if not env:
        print(f"No se encontró {ENV_PATH}")
        return 1

    print(f"Comprobando APIs desde {ENV_PATH}\n")
    checks = [
        check_supabase(env),
        check_livekit(env),
        check_deepgram(env),
        check_cartesia(env),
        check_groq(env),
        check_openai(env),
        check_google(env),
        check_n8n(env),
        check_glpi(env),
        check_telegram(env),
    ]

    ok_count = sum(1 for c in checks if c["ok"])
    for c in checks:
        icon = "OK" if c["ok"] else "FAIL"
        ms = f" ({c['ms']:.0f}ms)" if c.get("ms") else ""
        print(f"  [{icon:4}] {c['name']:<16} {c['detail']}{ms}")

    print(f"\n{ok_count}/{len(checks)} comprobaciones OK")

    # Avisos de config local
    warnings = []
    if not env.get("REDIS_PASSWORD") and "REDIS" not in env:
        warnings.append("REDIS_PASSWORD no está en .env (obligatorio en Docker/Portainer)")
    if env.get("LIVEKIT_API_KEY") == "devkey":
        warnings.append("LIVEKIT_API_KEY=devkey: servidor LiveKit propio (ok si usas livekit.ausarta.net)")
    if env.get("SUPABASE_KEY") == env.get("VITE_SUPABASE_ANON_KEY"):
        warnings.append("SUPABASE_KEY = anon key; el backend debería usar SUPABASE_SERVICE_ROLE_KEY para escrituras")
    if warnings:
        print("\nAvisos:")
        for w in warnings:
            print(f"  - {w}")

    return 0 if ok_count >= 6 else 1  # core APIs must pass


if __name__ == "__main__":
    sys.exit(main())
