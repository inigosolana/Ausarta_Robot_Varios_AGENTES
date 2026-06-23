from dotenv import load_dotenv

load_dotenv()

from agents import CallSession, DynamicAgent, entrypoint  # noqa: E402
from agents.entrypoint import server  # noqa: E402
from agents.dynamic_agent import (  # noqa: E402
    BRIDGE_SERVER_URL_INTERNAL,
    DISPATCH_AGENT_NAME,
    anonymize_text,
    cli,
    detect_language,
    logger,
    normalize_goodbye_message,
    server,
)

__all__ = [
    "DynamicAgent",
    "CallSession",
    "anonymize_text",
    "detect_language",
    "normalize_goodbye_message",
    "entrypoint",
    "server",
    "cli",
]


if __name__ == "__main__":
    logger.info(
        "🤖 Arrancando worker LiveKit | agent_name=%s | livekit_url=%s | bridge=%s",
        DISPATCH_AGENT_NAME,
        (__import__("os").getenv("LIVEKIT_URL") or "NO SET"),
        BRIDGE_SERVER_URL_INTERNAL,
    )
    cli.run_app(server)
