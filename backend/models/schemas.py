from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class VoiceAgentCreate(BaseModel):
    name: str
    company_context: Optional[str] = None
    enthusiasm_level: Optional[str] = "Normal"
    voice_id: Optional[str] = None
    speaking_speed: Optional[float] = 1.0

class VoiceAgentUpdate(BaseModel):
    instructions: Optional[str] = None
    greeting: Optional[str] = None
    company_context: Optional[str] = None
    enthusiasm_level: Optional[str] = None
    voice_id: Optional[str] = None
    speaking_speed: Optional[float] = None
    agent_config: Optional[dict] = None # Para guardar configuraciones completas si se necesita

class ExtractionSchemaProperty(BaseModel):
    key: str
    type: str # 'boolean', 'number', 'enum', 'text'
    label: str
    options: Optional[List[str]] = None

class CampaignCreate(BaseModel):
    name: str
    agent_id: int
    scheduled_time: Optional[datetime] = None
    leads_csv: Optional[str] = None # Contenido CSV en base64 o raw string
    retries_count: int = 3
    retry_interval: int = 60 # Minutos - Default 1 hora
    interval_minutes: int = 2 # Espera entre leads (Campañas por Goteo)
    extraction_schema: Optional[List[ExtractionSchemaProperty]] = None

class CampaignLeadModel(BaseModel):
    phone_number: str
    customer_name: str
    id: Optional[int] = None # ID opcional si viene de fuera

class CampaignModel(BaseModel):
    name: str
    agent_id: int
    empresa_id: Optional[int] = None
    status: str = "pending"
    scheduled_time: Optional[datetime] = None
    retries_count: int = 3
    retry_interval: int = 180
    retry_unit: str = "minutes"
    interval_minutes: int = 2
    extraction_schema: Optional[List[ExtractionSchemaProperty]] = None

class LlmConfig(BaseModel):
    llm_provider: str
    llm_model: str
    stt_provider: str
    stt_model: str
    tts_provider: str
    tts_model: str
    tts_voice: str
    language: str

class EncuestaData(BaseModel):
    id_encuesta: int
    status: Optional[str] = None
    nota_comercial: Optional[int] = None
    nota_instalador: Optional[int] = None
    nota_rapidez: Optional[int] = None
    comentarios: Optional[str] = None
    transcription: Optional[str] = None
    seconds_used: Optional[int] = None
    llm_model: Optional[str] = None
    datos_extra: Optional[dict] = None

class CallEndRequest(BaseModel):
    nombre_sala: str


class TestOutboundCallRequest(BaseModel):
    """Payload para pruebas de llamada saliente vía LiveKit SIP."""
    phone_number: str
    empresa_id: str
    survey_id: str

class AIPromptRequest(BaseModel):
    user_request: str
    empresa_id: Optional[int] = None
    current_name: Optional[str] = None
    current_use_case: Optional[str] = None
    current_greeting: Optional[str] = None
    current_description: Optional[str] = None
    current_instructions: Optional[str] = None
    current_critical_rules: Optional[str] = None

class AssistantChatRequest(BaseModel):
    message: str
    empresa_id: Optional[int] = None
    user_id: Optional[str] = None

class AssistantToolResponse(BaseModel):
    response: str


# ── Yeastar PBX integration (P-Series) ─────────────────────────────────────────

class YeastarPSeriesConfigBase(BaseModel):
    """Fields shared between create and update."""
    yeastar_pbx_url: str
    yeastar_client_id: str


class YeastarPSeriesConfigCreate(YeastarPSeriesConfigBase):
    """Used on POST — includes the secret (write-only)."""
    yeastar_client_secret: str
    empresa_id: Optional[int] = None


class YeastarPSeriesConfigTest(BaseModel):
    """Payload for the /test endpoint — never persisted."""
    yeastar_pbx_url: str
    yeastar_client_id: str
    yeastar_client_secret: str
    empresa_id: Optional[int] = None


class YeastarPSeriesConfigResponse(YeastarPSeriesConfigBase):
    """Returned by GET — secret is masked."""
    empresa_id: int
    yeastar_client_secret: str # Will return '********' if set

    class Config:
        from_attributes = True


class CallTransferRequest(BaseModel):
    """Transferencia a agente humano (agente LiveKit → backend → Yeastar)."""
    room_name: str
    empresa_id: int
    call_id: str
    extension: str = "1000"
    survey_id: Optional[int] = None
    motivo: Optional[str] = None


class TelephonyTransferRequest(BaseModel):
    """Solicitud de transferencia LiveKit → extensión Yeastar del tenant."""
    survey_id: int
    room_name: str
    motivo: Optional[str] = None
    target_extension: Optional[str] = None
    yeastar_call_id: Optional[str] = None

