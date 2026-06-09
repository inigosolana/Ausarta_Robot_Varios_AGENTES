from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # LiveKit
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""
    livekit_room_prefix: str = "llamada_ausarta_"

    # Modelos por defecto
    default_cartesia_voice_id: str = "b5aa8098-49ef-475d-89b0-c9262ecf33fd"
    default_stt_model: str = "nova-3"
    default_tts_model: str = "sonic-multilingual"
    default_llm_model: str = "llama-3.3-70b-versatile"

    # Tiempos del agente
    agent_greeting_delay_seconds: float = 0.15
    agent_hangup_delay_seconds: float = 0.15
    agent_silence_reprompt_seconds: float = 7.0
    agent_amd_window_seconds: float = 15.0
    agent_call_timeout_seconds: int = 600
    agent_config_cache_ttl: int = 300

    # Drip campaign
    drip_cooldown_min_seconds: int = 120
    drip_cooldown_max_seconds: int = 180

    # Infraestructura
    redis_url: str = "redis://redis:6379/0"
    bridge_server_url_internal: str

    class Config:
        env_file = ".env"

    @property
    def default_cartesia_voice(self) -> str:
        return self.default_cartesia_voice_id

    @property
    def agent_greeting_delay(self) -> float:
        return self.agent_greeting_delay_seconds

    @property
    def agent_hangup_delay(self) -> float:
        return self.agent_hangup_delay_seconds

    @property
    def drip_cooldown_min(self) -> int:
        return self.drip_cooldown_min_seconds

    @property
    def drip_cooldown_max(self) -> int:
        return self.drip_cooldown_max_seconds


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
