from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        populate_by_name=True,
    )

    # LiveKit
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""
    livekit_room_prefix: str = "llamada_ausarta_"

    # Modelos por defecto
    default_cartesia_voice: str = Field(
        default="de38f545-c574-44e8-9b54-a7d6fec1c6b1",
        validation_alias="DEFAULT_CARTESIA_VOICE_ID",
    )
    default_stt_model: str = "nova-3"
    default_tts_model: str = "sonic-3"
    default_llm_model: str = "llama-3.3-70b-versatile"

    # Tiempos del agente
    agent_greeting_delay: float = Field(default=0.15, validation_alias="AGENT_GREETING_DELAY_SECONDS")
    agent_hangup_delay: float = Field(default=0.15, validation_alias="AGENT_HANGUP_DELAY_SECONDS")
    agent_silence_reprompt_seconds: float = 7.0
    agent_amd_window_seconds: float = 15.0
    agent_call_timeout_seconds: int = 600
    agent_config_cache_ttl: int = 300

    # Drip campaign
    drip_cooldown_min: int = Field(default=120, validation_alias="DRIP_COOLDOWN_MIN_SECONDS")
    drip_cooldown_max: int = Field(default=180, validation_alias="DRIP_COOLDOWN_MAX_SECONDS")

    # Infraestructura
    redis_url: str = "redis://redis:6379/0"
    bridge_server_url_internal: str


@lru_cache()
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    """Limpia la caché de settings (útil en tests para evitar fugas de estado)."""
    get_settings.cache_clear()


settings = get_settings()
