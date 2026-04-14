from fastapi import APIRouter
from fastapi.responses import JSONResponse
from typing import Optional
from services.supabase_service import supabase, sb_query
from models.schemas import AIPromptRequest
from datetime import datetime
import os
import json
import logging
import aiohttp
import re
from openai import AsyncOpenAI

logger = logging.getLogger("api-backend")

router = APIRouter(prefix="/api", tags=["settings"])


async def _fetch_wikipedia_context(company_name: str) -> str:
    """Busca un resumen breve en Wikipedia para la empresa."""
    query_url = "https://es.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "list": "search",
        "srsearch": company_name,
        "format": "json",
        "utf8": 1,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(query_url, params=params, timeout=8) as resp:
                if resp.status != 200:
                    return ""
                data = await resp.json()
                results = (data.get("query") or {}).get("search") or []
                if not results:
                    return ""
                top_title = results[0].get("title")
                if not top_title:
                    return ""

            summary_url = f"https://es.wikipedia.org/api/rest_v1/page/summary/{top_title.replace(' ', '_')}"
            async with session.get(summary_url, timeout=8) as resp2:
                if resp2.status != 200:
                    return ""
                summary_data = await resp2.json()
                extract = (summary_data.get("extract") or "").strip()
                return extract
    except Exception:
        return ""


async def _fetch_duckduckgo_context(company_name: str) -> str:
    """Obtiene contexto público desde DuckDuckGo Instant Answer API."""
    url = "https://api.duckduckgo.com/"
    params = {
        "q": company_name,
        "format": "json",
        "no_redirect": 1,
        "no_html": 1,
        "skip_disambig": 1,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=8) as resp:
                if resp.status != 200:
                    return ""
                data = await resp.json()
                abstract = (data.get("AbstractText") or "").strip()
                if abstract:
                    return abstract
                related = data.get("RelatedTopics") or []
                snippets = []
                for item in related[:5]:
                    if isinstance(item, dict) and item.get("Text"):
                        snippets.append(item["Text"].strip())
                return " ".join(snippets).strip()
    except Exception:
        return ""


async def _build_company_context_with_ai(company_name: str, web_context: str) -> str:
    """
    Convierte información web en contexto accionable para el agente.
    Siempre devuelve texto útil (aunque la web no aporte datos).
    """
    openai_key = os.getenv("OPENAI_API_KEY")
    if not openai_key:
        if web_context:
            return (
                f"{company_name}: {web_context}\n"
                "Usa un tono cercano y profesional. Si falta algun dato concreto, dilo con transparencia y no inventes informacion."
            )
        return (
            f"{company_name}: empresa sin contexto publico suficiente en este momento.\n"
            "Responde de forma general, pide confirmacion cuando falte informacion y no inventes datos."
        )

    client = AsyncOpenAI(api_key=openai_key)
    safe_context = (web_context or "").strip()
    system_prompt = """
Eres un especialista en configuración de agentes de voz para atención telefónica.
Debes generar un "Contexto de Empresa" práctico para que un agente responda con seguridad.

Salida:
- Texto en español, 1 bloque, sin markdown.
- 6 a 10 líneas máximo.
- Incluye: qué hace la empresa, público objetivo, propuesta de valor, tono recomendado, y límites (qué NO inventar).
- Si faltan datos, indícalo de forma explícita y añade una pauta de respuesta segura.
"""
    user_prompt = (
        f"Empresa: {company_name}\n\n"
        f"Información recopilada de internet:\n{safe_context if safe_context else '(sin datos concluyentes)'}\n\n"
        "Genera el contexto de empresa para usar en un agente telefónico."
    )
    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        max_tokens=350,
    )
    return (response.choices[0].message.content or "").strip()


@router.post("/ai/company-context")
async def generate_company_context(payload: dict):
    """
    Genera contexto de empresa usando información pública de internet.
    """
    try:
        empresa_id = payload.get("empresa_id")
        company_name = (payload.get("company_name") or "").strip()

        if not company_name and empresa_id and supabase:
            try:
                emp_res = await sb_query(
                    lambda: supabase.table("empresas").select("nombre").eq("id", int(empresa_id)).limit(1).execute()
                )
                if emp_res.data:
                    company_name = (emp_res.data[0].get("nombre") or "").strip()
            except Exception as e_emp:
                logger.warning(f"No se pudo resolver nombre de empresa para contexto web: {e_emp}")

        if not company_name:
            return JSONResponse(status_code=400, content={"success": False, "error": "company_name o empresa_id es requerido"})

        # Fuentes públicas sin clave
        wiki_text = await _fetch_wikipedia_context(company_name)
        ddg_text = await _fetch_duckduckgo_context(company_name)
        merged_context = "\n".join([s for s in [wiki_text, ddg_text] if s]).strip()
        merged_context = re.sub(r"\s+", " ", merged_context).strip()

        ai_context = await _build_company_context_with_ai(company_name, merged_context)
        return {"success": True, "company_context": ai_context, "company_name": company_name}
    except Exception as e:
        logger.error(f"Error generating company context: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})

@router.post("/ai/generate-prompt")
async def generate_ai_prompt(req: AIPromptRequest):
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        empresa_name = "la empresa"
        if req.empresa_id and supabase:
            try:
                emp_res = await sb_query(
                    lambda: supabase.table("empresas").select("nombre").eq("id", req.empresa_id).execute()
                )
                if emp_res.data:
                    empresa_name = emp_res.data[0]["nombre"]
            except Exception as e_emp:
                logger.warning(f"No se pudo cargar nombre de empresa: {e_emp}")

        system_prompt = f"""
Eres un experto en diseñar e implementar Agentes Telefónicos de IA.
El usuario te dará un propósito general o unas preguntas que quiere hacer en su campaña. O tal vez te pida editar un agente existente.
Tu tarea es devolver la configuración del agente EN FORMATO JSON ESTRICTO, con las siguientes claves:
- "name": Un nombre creativo y común (ej: Dakota, Carlos, Laura) para el agente.
- "use_case": Frase muy breve de qué va (ej: Encuesta de satisfacción).
- "greeting": El saludo inicial. Como regla general, debe decir que es el asistente virtual de "{empresa_name}". Ejemplo: "Hola, soy [name], el asistente virtual de {empresa_name}. ¿Tiene un momento?".
- "description": Breve descripción interna del propósito.
- "instructions": Todo el texto del prompt, en español, con las reglas de cómo debe comportarse. Si es una encuesta, incluye explícitamente "Pregunta 1:", "Pregunta 2:", etc. como instrucciones de paso a paso.
- "critical_rules": Una lista de 3 a 5 reglas críticas e innegociables que el agente debe seguir pase lo que pase (ej: "No inventar datos", "Siempre despedirse", "No saltar a la siguiente pregunta sin confirmar").
- "tipo_resultados" (opcional): "ENCUESTA_NUMERICA" si solo preguntas de puntuación 1-10; "ENCUESTA_MIXTA" si combina numéricas + pregunta abierta o condicional; "PREGUNTAS_ABIERTAS" si son solo respuestas libres.

CONDICIONALES OBLIGATORIOS: Si el usuario pide condicionales (ej: "si responde X pregunta Y", "si la nota es 1-3 pregunta el motivo"), DEBES incluirlos explícitamente en "instructions" con la estructura:
  - "PASO N: CONDICIONAL (Pregunta X). - SI [condición]: [acción/pregunta]. - SI [otra condición]: [otra acción]. - En caso contrario: [acción por defecto]."
El agente ejecutará la lógica leyendo el prompt. Escribe los condicionales de forma clara para que el LLM los siga.

SOLO DEBES DEVOLVER EL TEXTO EN FORMATO JSON, QUE SEA PUEDE CARGAR MEDIANTE JSON.LOADS(). SIN ACENTOS EN LAS CLAVES DEL JSON (sólo usa las indicadas en inglés). SI USAS MARKDOWN PARA EL JSON (```json), EL SISTEMA FALLARÁ. DEVUELVE DIRECTAMENTE `{{"name": ...}}`.
"""
        
        if any([req.current_name, req.current_instructions, req.current_greeting]):
            system_prompt += f"""
CONFIGURACIÓN ACTUAL DEL AGENTE:
- Nombre: {req.current_name or ''}
- Caso de uso: {req.current_use_case or ''}
- Saludo: {req.current_greeting or ''}
- Descripción: {req.current_description or ''}
- Instrucciones: {req.current_instructions or ''}
- Reglas críticas: {req.current_critical_rules or ''}

IMPORTANTE: El usuario quiere ACTUALIZAR este agente con el nuevo request. Modifica solo lo que pida el usuario y mantén el resto de la configuración si sigue teniendo sentido.
"""
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": req.user_request}
            ],
            temperature=0.7,
            max_tokens=1500
        )
        
        raw_content = response.choices[0].message.content.strip()
        if raw_content.startswith("```json"):
            raw_content = raw_content[7:-3].strip()
        elif raw_content.startswith("```"):
            raw_content = raw_content[3:-3].strip()
            
        data = json.loads(raw_content)
        return {"success": True, "data": data}
    except Exception as e:
        logger.error(f"Error AI Prompt Generator: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@router.get("/ai/config")
async def get_ai_config():
    if not supabase: return {"llm_provider": "groq"}
    try:
        res = await sb_query(lambda: supabase.table("ai_config").select("*").limit(1).execute())
        return res.data[0] if res.data else {}
    except Exception as e:
        logger.error(f"Error AI config: {e}")
        return {}

@router.post("/ai/config")
async def update_ai_config(config: dict):
    if not supabase: return {"error": "No DB"}
    try:
        curr = await sb_query(lambda: supabase.table("ai_config").select("id").limit(1).execute())
        if not curr.data:
            await sb_query(lambda: supabase.table("ai_config").insert(config).execute())
        else:
            first_id = curr.data[0]['id']
            valid_fields = ["llm_provider", "llm_model", "tts_provider", "tts_model", "tts_voice", "stt_provider", "stt_model"]
            clean_config = {k: v for k, v in config.items() if k in valid_fields}
            clean_config["updated_at"] = datetime.utcnow().isoformat()
            await sb_query(lambda: supabase.table("ai_config").update(clean_config).eq("id", first_id).execute())

        return {"status": "ok", "message": "Modelos actualizados"}
    except Exception as e:
        logger.error(f"Error updating AI config: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.get("/settings")
async def get_settings_alias():
    return await get_ai_config()

@router.post("/settings")
async def update_settings_alias(config: dict):
    return await update_ai_config(config)
