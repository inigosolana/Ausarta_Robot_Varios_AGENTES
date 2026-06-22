from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
import os
import json
import logging
from openai import AsyncOpenAI
from models.schemas import AssistantChatRequest
from services.supabase_service import supabase
from services.auth import CurrentUser, get_current_user

logger = logging.getLogger("api-backend")

router = APIRouter(prefix="/api/assistant", tags=["assistant"])

_openai_client: AsyncOpenAI | None = None


def _get_openai_client() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise HTTPException(status_code=503, detail="OPENAI_API_KEY no configurada")
        _openai_client = AsyncOpenAI(api_key=key)
    return _openai_client


@router.post("/chat")
async def assistant_chat(
    req: AssistantChatRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    client = _get_openai_client()
    effective_empresa_id = req.empresa_id if current_user.role == "superadmin" and req.empresa_id else current_user.empresa_id

    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_platform_stats",
                "description": "Obtiene estadísticas de llamadas y uso de la plataforma de la base de datos.",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "create_voice_agent",
                "description": "Crea un nuevo agente de voz en la plataforma.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Nombre del agente"},
                        "use_case": {"type": "string", "description": "Caso de uso resumido"},
                        "description": {"type": "string", "description": "Descripción general"},
                        "instructions": {"type": "string", "description": "System prompt o instrucciones del agente"},
                        "greeting": {"type": "string", "description": "Mensaje de saludo inicial"}
                    },
                    "required": ["name", "use_case", "description", "instructions", "greeting"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "explain_feature",
                "description": "Explica cómo usar una función específica de la plataforma consultando la base de conocimientos.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "feature_name": {"type": "string", "description": "Nombre de la función a explicar"}
                    },
                    "required": ["feature_name"]
                }
            }
        }
    ]

    system_prompt = f"Eres Ausarta Copilot, el asistente inteligente de la plataforma 'Ausarta Voice AI'. Eres un experto en la plataforma. Ahora mismo estás hablando con un usuario de la empresa {effective_empresa_id}. Usa las herramientas a tu disposición si es necesario para responder o realizar acciones. Si no necesitas herramientas, simplemente responde de manera amigable y servicial. Puedes usar formato Markdown para presentar la información."

    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": req.message}
            ],
            tools=tools,
            tool_choice="auto",
            max_tokens=2000,
        )

        response_message = response.choices[0].message
        tool_calls = response_message.tool_calls

        if tool_calls:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": req.message},
                response_message
            ]

            for tool_call in tool_calls:
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments)

                tool_result = ""

                if function_name == "get_platform_stats":
                    if effective_empresa_id:
                        res = supabase.table("encuestas").select("status").eq("empresa_id", effective_empresa_id).execute()
                    else:
                        res = supabase.table("encuestas").select("status").execute()

                    if res.data:
                        total = len(res.data)
                        completed = len([x for x in res.data if x.get("status") == "completed"])
                        tool_result = json.dumps({"total_llamadas": total, "llamadas_completadas": completed})
                    else:
                        tool_result = json.dumps({"total_llamadas": 0, "llamadas_completadas": 0})

                elif function_name == "create_voice_agent":
                    resolved_type = "ENCUESTA_NUMERICA"
                    insert_data = {
                        "empresa_id": effective_empresa_id,
                        "name": str(function_args.get("name", ""))[:100],
                        "use_case": str(function_args.get("use_case", ""))[:500],
                        "description": str(function_args.get("description", ""))[:2000],
                        "instructions": str(function_args.get("instructions", ""))[:5000],
                        "greeting": str(function_args.get("greeting", ""))[:500],
                        "tipo_resultados": resolved_type,
                        "agent_type": resolved_type,
                        "survey_type": "numeric",
                    }
                    res = supabase.table("agent_config").insert(insert_data).execute()
                    if res.data:
                        new_agent_id = res.data[0]["id"]
                        supabase.table("ai_config").insert({
                            "agent_id": new_agent_id,
                            "llm_provider": "groq",
                            "llm_model": "llama-3.3-70b-versatile",
                            "tts_provider": "cartesia",
                            "tts_model": "sonic-multilingual",
                            "tts_voice": "b5aa8098-49ef-475d-89b0-c9262ecf33fd",
                            "stt_provider": "deepgram",
                            "stt_model": "nova-2",
                            "language": "es"
                        }).execute()
                        tool_result = json.dumps({"status": "success", "agent_id": new_agent_id, "message": "Agente creado con éxito en Supabase"})
                    else:
                        tool_result = json.dumps({"status": "error", "message": "Falló al crear el agente"})

                elif function_name == "explain_feature":
                    feature = str(function_args.get("feature_name", ""))[:200]
                    tool_result = json.dumps({"status": "success", "info": f"La función '{feature}' es una de las principales utilidades de la plataforma. Dile al usuario que puede acceder a ella desde el menú lateral para ejecutar sus flujos automatizados."})

                else:
                    tool_result = json.dumps({"error": "Unknown function"})

                messages.append(
                    {
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": function_name,
                        "content": tool_result,
                    }
                )

            second_response = await client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                max_tokens=2000,
            )
            return {"response": second_response.choices[0].message.content}

        else:
            return {"response": response_message.content}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error in assistant chat: %s", e, exc_info=True)
        return JSONResponse(status_code=500, content={"error": "Error interno del servidor"})
