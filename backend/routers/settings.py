from fastapi import APIRouter
from fastapi.responses import JSONResponse
from typing import Optional
from services.supabase_service import supabase
from models.schemas import AIPromptRequest
from datetime import datetime
import os
import json
import logging

logger = logging.getLogger("api-backend")

router = APIRouter(prefix="/api", tags=["settings"])

@router.post("/ai/generate-prompt")
async def generate_ai_prompt(req: AIPromptRequest):
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        empresa_name = "la empresa"
        if req.empresa_id and supabase:
            try:
                emp_res = supabase.table("empresas").select("nombre").eq("id", req.empresa_id).execute()
                if emp_res.data:
                    empresa_name = emp_res.data[0]["nombre"]
            except Exception as e_emp:
                logger.warning(f"No se pudo cargar nombre de empresa: {e_emp}")

        system_prompt = f"""
Eres un experto en diseñar e implementar Agentes Telefónicos de IA.
El usuario te dará un propósito general o unas preguntas que quiere hacer en su campaña. O tal vez te pida editar un agente existente.
Tu tarea es devolver la configuración del agente EN FORMATO JSON ESTRICTO, con las siguientes claves y nada más:
- "name": Un nombre creativo y común (ej: Dakota, Carlos, Laura) para el agente.
- "use_case": Frase muy breve de qué va (ej: Encuesta de satisfacción).
- "greeting": El saludo inicial. Como regla general, debe decir que es el asistente virtual de "{empresa_name}". Ejemplo: "Hola, soy [name], el asistente virtual de {empresa_name}. ¿Tiene un momento?".
- "description": Breve descripción interna del propósito.
- "instructions": Todo el texto del prompt, en español, con las reglas de cómo debe comportarse. Si es una encuesta, incluye explícitamente "Pregunta 1:", "Pregunta 2:", etc. como instrucciones de paso a paso.
- "critical_rules": Una lista de 3 a 5 reglas críticas e innegociables que el agente debe seguir pase lo que pase (ej: "No inventar datos", "Siempre despedirse", "No saltar a la siguiente pregunta sin confirmar").

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
        res = supabase.table("ai_config").select("*").limit(1).execute()
        return res.data[0] if res.data else {}
    except Exception as e:
        logger.error(f"Error AI config: {e}")
        return {}

@router.post("/ai/config")
async def update_ai_config(config: dict):
    if not supabase: return {"error": "No DB"}
    try:
        curr = supabase.table("ai_config").select("id").limit(1).execute()
        if not curr.data:
            supabase.table("ai_config").insert(config).execute()
        else:
            first_id = curr.data[0]['id']
            # Filtrar
            valid_fields = ["llm_provider", "llm_model", "tts_provider", "tts_model", "tts_voice", "stt_provider", "stt_model"]
            clean_config = {k: v for k, v in config.items() if k in valid_fields}
            clean_config["updated_at"] = datetime.utcnow().isoformat()
            
            supabase.table("ai_config").update(clean_config).eq("id", first_id).execute()
            
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
