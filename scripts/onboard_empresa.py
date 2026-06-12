#!/usr/bin/env python3
"""
onboard_empresa.py — Script CLI para automatizar el alta de una empresa nueva.

Crea las filas base en Supabase (empresa, empresa_limits, agente por defecto).
NO gestiona credenciales reales ni configuración de telefonía.

Uso:
    python scripts/onboard_empresa.py \
        --nombre "Empresa Ejemplo S.L." \
        --email admin@empresa.com \
        [--plan standard] \
        [--rpm 120] \
        [--dry-run]

Requisitos:
    pip install python-dotenv supabase

Variables de entorno necesarias:
    SUPABASE_URL, SUPABASE_SERVICE_KEY (o SUPABASE_KEY)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# ── Path setup ──────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend" if (ROOT / "backend" / "config.py").exists() else ROOT
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    load_dotenv(ROOT / "stack.env")
except ImportError:
    pass

# ── Colores terminal ──────────────────────────────────────────────────────────
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"
BOLD = "\033[1m"

def ok(msg: str) -> None:
    print(f"{GREEN}✅ {msg}{RESET}")

def warn(msg: str) -> None:
    print(f"{YELLOW}⚠️  {msg}{RESET}")

def err(msg: str) -> None:
    print(f"{RED}❌ {msg}{RESET}")

def info(msg: str) -> None:
    print(f"   {msg}")


# ── Supabase client ───────────────────────────────────────────────────────────

def _get_supabase():
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY", "")
    if not url or not key:
        err("SUPABASE_URL y SUPABASE_SERVICE_KEY son requeridas.")
        sys.exit(1)
    try:
        from supabase import create_client
        return create_client(url, key)
    except ImportError:
        err("Instala supabase: pip install supabase")
        sys.exit(1)


# ── Pasos del onboarding ──────────────────────────────────────────────────────

def step1_create_empresa(sb, nombre: str, email: str, plan: str, dry_run: bool) -> int | None:
    """Crear fila en tabla empresas. Devuelve empresa_id."""
    print(f"\n{BOLD}[ Paso 1 ] Crear empresa{RESET}")
    info(f"Nombre: {nombre}")
    info(f"Plan:   {plan}")
    info(f"Email:  {email}")

    if dry_run:
        warn("DRY-RUN: no se creó la empresa. empresa_id ficticio = 9999")
        return 9999

    try:
        res = sb.table("empresas").insert({
            "nombre": nombre,
            "plan": plan,
            "activo": True,
            "datos_extra": json.dumps({
                "contacto_admin": email,
                "onboarding": "script_v2"
            }),
        }).execute()
        if not res.data:
            err("Error al crear empresa: respuesta vacía")
            return None
        empresa_id = res.data[0]["id"]
        ok(f"Empresa creada → empresa_id = {empresa_id}")
        return empresa_id
    except Exception as exc:
        err(f"Error creando empresa: {exc}")
        return None


def step2_create_rate_limit(sb, empresa_id: int, rpm: int, dry_run: bool) -> bool:
    """Crear fila en empresa_limits."""
    print(f"\n{BOLD}[ Paso 2 ] Configurar rate limiting{RESET}")
    info(f"empresa_id: {empresa_id}  →  {rpm} req/min")

    if dry_run:
        warn("DRY-RUN: no se creó empresa_limits")
        return True

    try:
        sb.table("empresa_limits").upsert({
            "empresa_id": empresa_id,
            "rpm": rpm,
            "notas": "Creado por onboard_empresa.py",
        }).execute()
        ok(f"Rate limit configurado: {rpm} rpm")
        return True
    except Exception as exc:
        warn(f"No se pudo crear empresa_limits (tabla puede no existir aún): {exc}")
        info("Ejecuta la migración: backend/supabase/migrations/20260612_empresa_limits.sql")
        return False


def step3_create_default_agent(sb, empresa_id: int, nombre_empresa: str, dry_run: bool) -> int | None:
    """Crear agente por defecto."""
    print(f"\n{BOLD}[ Paso 3 ] Crear agente por defecto{RESET}")
    agent_nombre = "Asistente Virtual"
    instrucciones = (
        f"Eres {agent_nombre} de {nombre_empresa}. "
        "Atiende llamadas de forma profesional, amable y concisa. "
        "Responde siempre en el idioma del cliente."
    )
    info(f"Nombre agente: {agent_nombre}")
    info(f"Instrucciones: {instrucciones[:60]}...")

    if dry_run:
        warn("DRY-RUN: no se creó el agente. agent_id ficticio = 99")
        return 99

    try:
        res = sb.table("agentes").insert({
            "empresa_id": empresa_id,
            "nombre": agent_nombre,
            "tipo": "ASISTENTE_GENERAL",
            "activo": True,
            "instrucciones": instrucciones,
            "llm_model": "llama-3.3-70b-versatile",
            "idioma": "es",
            "personalidad": json.dumps({
                "entusiasmo": 0.6,
                "velocidad": 1.0,
                "critical_rules": "Nunca proporciones información falsa. Si no sabes algo, indícalo."
            }),
        }).execute()
        if not res.data:
            err("Error al crear agente: respuesta vacía")
            return None
        agent_id = res.data[0]["id"]
        ok(f"Agente creado → agent_id = {agent_id}")
        return agent_id
    except Exception as exc:
        err(f"Error creando agente: {exc}")
        return None


def step4_create_kb_placeholder(sb, empresa_id: int, agent_id: int, dry_run: bool) -> None:
    """Informar sobre la KB (no crea datos reales)."""
    print(f"\n{BOLD}[ Paso 4 ] Knowledge Base{RESET}")
    warn("Paso manual: sube documentos desde el panel → Knowledge Base")
    info("O usa el script:")
    info(f"  python scripts/excel_to_kb_chunks.py --empresa-id {empresa_id} --agent-id {agent_id} ...")
    info(f"  python scripts/ingest_kb_chunks.py --empresa-id {empresa_id} --file data/chunks.jsonl")


def step5_summary(empresa_id: int | None, agent_id: int | None, dry_run: bool) -> None:
    """Mostrar resumen final."""
    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}Resumen del onboarding{RESET}")
    print(f"{'='*60}")
    if dry_run:
        warn("Modo DRY-RUN — ningún dato fue guardado en la BD")
    if empresa_id:
        info(f"empresa_id  = {empresa_id}")
    if agent_id:
        info(f"agent_id    = {agent_id}")
    print()
    info("Pasos manuales pendientes:")
    info("  1. Crear usuario admin en Supabase Auth (ver docs/onboarding-empresa.md § Paso 2)")
    info("  2. Configurar telefonía Yeastar (si aplica) — § Paso 5")
    info("  3. Configurar BD externa del cliente (si aplica) — § Paso 6")
    info("  4. Ajustar personalidad del agente en el panel")
    print(f"\n{GREEN}{BOLD}¡Onboarding base completado!{RESET}")
    print(f"Ver checklist completo: {BOLD}docs/onboarding-empresa.md{RESET}\n")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Onboarding automatizado de empresa nueva en Ausarta Robot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python scripts/onboard_empresa.py --nombre "ACME S.L." --email admin@acme.es
  python scripts/onboard_empresa.py --nombre "Test Corp" --email test@test.com --dry-run
  python scripts/onboard_empresa.py --nombre "Pro Corp" --email pro@corp.com --plan pro --rpm 300
        """,
    )
    parser.add_argument("--nombre", required=True, help="Nombre comercial de la empresa")
    parser.add_argument("--email", required=True, help="Email del administrador de la empresa")
    parser.add_argument(
        "--plan",
        default="standard",
        choices=["standard", "pro", "enterprise"],
        help="Plan contratado (default: standard)",
    )
    parser.add_argument(
        "--rpm",
        type=int,
        default=120,
        help="Límite de requests por minuto (default: 120)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simular sin escribir en la BD",
    )
    args = parser.parse_args()

    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}🚀 Ausarta Robot — Onboarding de empresa nueva{RESET}")
    print(f"{'='*60}")
    if args.dry_run:
        warn("MODO DRY-RUN — no se escribirá en la base de datos\n")

    sb = None if args.dry_run else _get_supabase()

    empresa_id = step1_create_empresa(sb, args.nombre, args.email, args.plan, args.dry_run)
    if empresa_id is None and not args.dry_run:
        err("Abortando: no se pudo crear la empresa.")
        sys.exit(1)

    step2_create_rate_limit(sb, empresa_id, args.rpm, args.dry_run)
    agent_id = step3_create_default_agent(sb, empresa_id, args.nombre, args.dry_run)
    step4_create_kb_placeholder(sb, empresa_id, agent_id, args.dry_run)
    step5_summary(empresa_id, agent_id, args.dry_run)


if __name__ == "__main__":
    main()
