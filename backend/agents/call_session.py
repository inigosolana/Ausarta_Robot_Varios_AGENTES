from .dynamic_agent import CallSession

__all__ = ["CallSession"]

# CallSession.cleanup() libera bg_player, AgentSession, room y tareas en el finally del entrypoint.
