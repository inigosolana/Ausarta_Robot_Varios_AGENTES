#!/usr/bin/env python3
"""
Configura un agente inbound comercial de prueba (detecta o crea automáticamente).

  1. Busca agente inbound existente (nombre con 'inbound'/'recepcion' o SOPORTE_CLIENTE)
  2. Si no existe, lo crea en agent_config + ai_config
  3. Actualiza instructions + greeting comercial
  4. (Opcional) Ingesta KB de muestra

Uso:
  python scripts/setup_inbound_comercial_test.py --empresa_id 1 --ingest-kb
  python scripts/setup_inbound_comercial_test.py --empresa_id 1 --agent_id 7 --ingest-kb
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend" if (ROOT / "backend" / "config.py").exists() else ROOT
sys.path.insert(0, str(BACKEND))

if os.getenv("ENVIRONMENT", "production") == "development":
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")

from config import settings  # noqa: E402
from services.supabase_service import supabase, sb_query  # noqa: E402

INBOUND_AGENT_NAME = "Inbound Comercial - Ausarta"
INBOUND_COMERCIAL_INSTRUCTIONS = """Eres un comercial telefónico experto de Ausarta, empresa de telecomunicaciones.
Tu misión es atender consultas de clientes sobre servicios, tarifas y contrataciones.

COMPORTAMIENTO PRINCIPAL:
- Antes de responder cualquier pregunta sobre servicios, precios o cobertura,
  usa SIEMPRE la herramienta 'consultar_conocimiento'. Nunca inventes precios.
- Si el cliente pide comparar tarifas, extrae las 2-3 opciones más relevantes
  de la base de conocimiento y preséntaselas de forma clara y breve.
- Si no encuentras la información, di: "Déjame consultarlo con el equipo y
  te lo confirmo enseguida" — nunca inventes ni supongas.

ESTILO:
- Habla como una persona real: cálido, directo, sin sonar a robot.
- Respuestas cortas (máx 2-3 frases por turno).
- Una pregunta cada vez. Nunca lances listas largas de golpe.
- Si el cliente duda, ayúdale a decidir con una pregunta concreta:
  "¿Cuántos GB suele usar al mes?" o "¿Necesita movilidad o es para una sede fija?"

CIERRE:
- Cuando el cliente esté listo, ofrece pasarle con un comercial o tomar sus datos.
- Usa 'finalizar_llamada' con una despedida de máximo 6 palabras."""

INBOUND_GREETING = "Hola, le atiende Ausarta. ¿En qué puedo ayudarle hoy?"


def _is_inbound_candidate(agent: dict) -> bool:
    name = str(agent.get("name") or "").lower()
    agent_type = str(agent.get("agent_type") or agent.get("tipo_resultados") or "").upper()
    return (
        "inbound" in name
        or "recepcion" in name
        or "recepción" in name
        or agent_type == "SOPORTE_CLIENTE"
    )


async def find_inbound_agent(empresa_id: int) -> dict | None:
    """Devuelve el agente inbound preferido de la empresa (misma lógica que telephony)."""
    res = await sb_query(
        lambda: supabase.table("agent_config")
        .select("id, name, agent_type, tipo_resultados, empresa_id")
        .eq("empresa_id", empresa_id)
        .order("id")
        .execute()
    )
    agents = res.data or []
    if not agents:
        return None
    for agent in agents:
        if _is_inbound_candidate(agent):
            return agent
    return agents[0]


async def create_inbound_agent(empresa_id: int) -> int:
    """Crea agent_config + ai_config para inbound comercial."""
    db_config = {
        "name": INBOUND_AGENT_NAME,
        "instructions": INBOUND_COMERCIAL_INSTRUCTIONS,
        "critical_rules": "",
        "greeting": INBOUND_GREETING,
        "description": "Agente inbound comercial con KB de tarifas (prueba)",
        "use_case": "inbound_comercial",
        "company_context": "",
        "enthusiasm_level": "Normal",
        "voice_id": settings.default_cartesia_voice_id,
        "speaking_speed": 1.0,
        "empresa_id": empresa_id,
        "tipo_resultados": "SOPORTE_CLIENTE",
        "agent_type": "SOPORTE_CLIENTE",
        "survey_type": "SOPORTE_CLIENTE",
        "agent_mode": "prompt",
        "workflow_variables": {},
    }
    res = await sb_query(
        lambda: supabase.table("agent_config").insert(db_config).execute()
    )
    if not res.data:
        raise SystemExit("❌ No se pudo crear el agente inbound.")
    new_id = int(res.data[0]["id"])

    ai_config = {
        "agent_id": new_id,
        "llm_provider": "groq",
        "llm_model": settings.default_llm_model,
        "tts_provider": "cartesia",
        "tts_model": settings.default_tts_model,
        "tts_voice": settings.default_cartesia_voice_id,
        "stt_provider": "deepgram",
        "stt_model": settings.default_stt_model,
        "language": "es",
    }
    await sb_query(
        lambda: supabase.table("ai_config").insert(ai_config).execute()
    )
    print(f"✅ Agente inbound creado: id={new_id} nombre='{INBOUND_AGENT_NAME}'")
    return new_id


async def ensure_inbound_agent(empresa_id: int, agent_id: int | None = None) -> int:
    """Resuelve agent_id: explícito → buscar inbound → crear."""
    if not supabase:
        raise SystemExit("❌ Supabase no configurado.")

    if agent_id is not None:
        res = await sb_query(
            lambda: supabase.table("agent_config")
            .select("id")
            .eq("id", agent_id)
            .eq("empresa_id", empresa_id)
            .limit(1)
            .execute()
        )
        if not res.data:
            raise SystemExit(f"❌ agent_id={agent_id} no existe para empresa_id={empresa_id}")
        return agent_id

    existing = await find_inbound_agent(empresa_id)
    if existing:
        aid = int(existing["id"])
        print(f"ℹ️  Agente inbound detectado: id={aid} nombre='{existing.get('name')}'")
        return aid

    return await create_inbound_agent(empresa_id)


async def update_agent(agent_id: int, empresa_id: int) -> None:
    payload = {
        "instructions": INBOUND_COMERCIAL_INSTRUCTIONS,
        "greeting": INBOUND_GREETING,
        "agent_type": "SOPORTE_CLIENTE",
        "tipo_resultados": "SOPORTE_CLIENTE",
        "survey_type": "SOPORTE_CLIENTE",
        "name": INBOUND_AGENT_NAME,
    }
    res = await sb_query(
        lambda: supabase.table("agent_config")
        .update(payload)
        .eq("id", agent_id)
        .eq("empresa_id", empresa_id)
        .execute()
    )
    if not res.data:
        raise SystemExit(f"❌ No se pudo actualizar agent_id={agent_id}")
    print(f"✅ Agente {agent_id} actualizado (prompt comercial inbound)")


async def ingest_kb(agent_id: int, empresa_id: int, kb_file: str) -> dict:
    kb_path = ROOT / kb_file
    if not kb_path.exists():
        raise SystemExit(f"❌ No existe {kb_path}")

    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "ingest_kb_chunks", ROOT / "scripts" / "ingest_kb_chunks.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)

    lines: list[str] = []
    for line in kb_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        obj["agent_id"] = agent_id
        obj["empresa_id"] = empresa_id
        lines.append(json.dumps(obj, ensure_ascii=False))

    tmp = ROOT / "data" / f"_kb_agent{agent_id}.jsonl"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        return await mod.ingest_jsonl(str(tmp), empresa_id=empresa_id)
    finally:
        tmp.unlink(missing_ok=True)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Setup inbound comercial (auto agent_id)")
    parser.add_argument("--empresa_id", type=int, default=1)
    parser.add_argument("--agent_id", type=int, default=None, help="Opcional; si se omite, detecta o crea")
    parser.add_argument("--ingest-kb", action="store_true")
    parser.add_argument("--kb-file", default="scripts/data/ausarta_kb_sample.jsonl")
    args = parser.parse_args()

    agent_id = await ensure_inbound_agent(args.empresa_id, args.agent_id)
    await update_agent(agent_id, args.empresa_id)

    if args.ingest_kb:
        result = await ingest_kb(agent_id, args.empresa_id, args.kb_file)
        print(f"✅ KB ingestada: {result}")

    print("\n📞 Listo para prueba inbound:")
    print(f"   - agent_id: {agent_id}")
    print(f"   - empresa_id: {args.empresa_id}")
    print("   - Yeastar enruta inbound → este agente (nombre con 'inbound' o SOPORTE_CLIENTE)")
    print("   - Pregunta de prueba: «¿Qué tarifas móviles tenéis?»")


if __name__ == "__main__":
    asyncio.run(main())
