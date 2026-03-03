from pydantic import BaseModel
from typing import Optional, Union, List
from datetime import datetime

class VoiceAgentCreate(BaseModel):
    name: str

class VoiceAgentUpdate(BaseModel):
    instructions: Optional[str] = None
    greeting: Optional[str] = None
    agent_config: Optional[dict] = None # Para guardar configuraciones completas si se necesita

class CampaignCreate(BaseModel):
    name: str
    agent_id: int
    scheduled_time: Optional[datetime] = None
    leads_csv: Optional[str] = None # Contenido CSV en base64 o raw string
    retries_count: int = 3
    retry_interval: int = 60 # Minutos - Default 1 hora

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

class CallEndRequest(BaseModel):
    nombre_sala: str

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
