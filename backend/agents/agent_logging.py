"""Configuración de logging del agente LiveKit (stdout + archivo solo en dev)."""

from __future__ import annotations

import logging
import os
import sys


def configure_agent_logging(logger_name: str = "agent-dynamic") -> logging.Logger:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(line_buffering=True)  # type: ignore[attr-defined]

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if os.getenv("ENVIRONMENT", "production").strip().lower() in (
        "development",
        "dev",
        "local",
    ):
        handlers.append(
            logging.FileHandler("agent.log", mode="a", encoding="utf-8")
        )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=handlers,
        force=True,
    )
    return logging.getLogger(logger_name)
