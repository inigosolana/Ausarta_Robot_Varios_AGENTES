from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, List, Literal, Any
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

class InboundCallRegisterRequest(BaseModel):
    """Registro de llamada entrante al conectar el agente (antes de colgar)."""

    empresa_id: int
    agent_id: Optional[int] = None
    telefono: str = ""
    room_name: str = ""
    agent_type: Optional[str] = None


class CallEndRequest(BaseModel):
    nombre_sala: str


class TestOutboundCallRequest(BaseModel):
    """Payload para pruebas de llamada saliente vía LiveKit SIP."""

    phone_number: str
    empresa_id: Optional[str] = None
    survey_id: Optional[str] = None
    """Si viene (p. ej. 'Ausarta'), localiza empresa_id ignorando mayúsculas."""
    from_empresa_nombre: Optional[str] = None

    @model_validator(mode="after")
    def _require_tenant_hint(self):
        emp = (self.empresa_id or "").strip()
        nom = (self.from_empresa_nombre or "").strip()
        if not emp and not nom:
            raise ValueError("Indica empresa_id o from_empresa_nombre")
        return self

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

YeastarApiMode = Literal["pseries", "cloud_pbx"]


class YeastarPSeriesConfigBase(BaseModel):
    """Fields shared between create and update."""
    yeastar_pbx_url: str
    yeastar_api_mode: YeastarApiMode = "pseries"
    yeastar_client_id: str
    enabled_capabilities: Optional[list[str]] = None


class YeastarPSeriesConfigCreate(YeastarPSeriesConfigBase):
    """Used on POST — includes the secret (write-only)."""
    yeastar_client_secret: Optional[str] = None
    empresa_id: Optional[int] = None
    ddi: Optional[str] = None  # DDI/número entrante del cliente, ej: "+34911234501"


class YeastarPSeriesConfigTest(BaseModel):
    """Payload for the /test endpoint — never persisted."""
    yeastar_pbx_url: str
    yeastar_api_mode: YeastarApiMode = "pseries"
    yeastar_client_id: str
    yeastar_client_secret: str
    empresa_id: Optional[int] = None


class YeastarPSeriesConfigResponse(YeastarPSeriesConfigBase):
    """Returned by GET — secret is masked."""
    empresa_id: int
    yeastar_client_secret: str  # Will return '********' if set
    enabled_capabilities: list[str] = []
    ddi: Optional[str] = None  # DDI/número entrante del cliente

    class Config:
        from_attributes = True


class CallTransferRequest(BaseModel):
    """
    Transferencia a agente humano (agente LiveKit → backend → Yeastar).

    El campo `extension` acepta tanto extensiones internas del PBX (ej. "1001")
    como números de teléfono externos en formato nacional o E.164 (ej. "612345678",
    "+34912345678"). El backend detecta automáticamente si es interno o externo
    consultando la tabla yeastar_extensions de la empresa.

    Para números externos se requiere que el Yeastar del cliente tenga configurada
    una ruta saliente válida. Ver docs/transferencias.md para configurar outbound_prefix.
    """
    room_name: str
    empresa_id: int
    call_id: str
    extension: str = Field(
        default="1000",
        description="Extensión interna (ej. '1001') o número externo (ej. '612345678', '+34612345678')",
    )
    survey_id: Optional[int] = None
    motivo: Optional[str] = None
    outbound_prefix: Optional[str] = Field(
        default=None,
        description="Prefijo de ruta saliente a anteponer para números externos (ej. '0', '9'). "
                    "Si es None, se usa el configurado en company_yeastar_configs o vacío.",
    )


class TelephonyTransferRequest(BaseModel):
    """
    Solicitud de transferencia LiveKit → destino Yeastar del tenant.

    El campo `target_extension` acepta tanto extensiones internas del PBX (ej. "1001")
    como números de teléfono externos en formato nacional o E.164 (ej. "612345678",
    "+34912345678"). Ver docs/transferencias.md.
    """
    survey_id: int
    room_name: str
    motivo: Optional[str] = None
    target_extension: Optional[str] = Field(
        default=None,
        description="Extensión interna o número externo (E.164 o nacional)",
    )
    yeastar_call_id: Optional[str] = None
    outbound_prefix: Optional[str] = Field(
        default=None,
        description="Prefijo de ruta saliente para números externos (ej. '0', '9').",
    )


# ── Workflow: tipos de nodo/edge y definición completa ───────────────────────

class WorkflowNodePosition(BaseModel):
    x: float = 0.0
    y: float = 0.0


class WorkflowNode(BaseModel):
    id: str
    type: Literal["message", "question", "condition", "llm_free", "transfer", "end"]
    label: str = ""
    content: Optional[str] = None
    prompt: Optional[str] = None          # sub-prompt libre (llm_free / mixed)
    variable: Optional[str] = None        # nombre de variable donde guardar respuesta
    options: Optional[List[str]] = None   # opciones de respuesta para tipo question
    position: Optional[WorkflowNodePosition] = None


class WorkflowEdge(BaseModel):
    id: str
    source: str
    target: str
    condition: Optional[str] = None       # None → default; expr → evaluación condicional


class WorkflowDefinition(BaseModel):
    nodes: List[WorkflowNode] = []
    edges: List[WorkflowEdge] = []
    start_node: str = ""


class AgentModeConfig(BaseModel):
    """
    PARTE 5: campos de workflow que se añaden a los endpoints de agente.
    Usado tanto en creación como en actualización.
    """
    agent_mode: Literal["prompt", "workflow", "mixed"] = "prompt"
    workflow_definition: Optional[dict] = None   # Se acepta como dict bruto para flexibilidad
    workflow_variables: dict = {}


class WorkflowValidateRequest(BaseModel):
    """Body del endpoint POST /api/agents/{id}/workflow/validate."""
    workflow_definition: dict
    agent_mode: Literal["workflow", "mixed"] = "workflow"
    base_instructions: str = ""


class WorkflowValidateResponse(BaseModel):
    """Respuesta del endpoint de validación/previsualización del workflow."""
    compiled_prompt: str
    steps: List[dict]
    node_count: int
    step_count: int
    warnings: List[str] = []

