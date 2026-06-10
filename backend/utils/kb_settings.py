"""Resolución de configuración KB / internet por empresa y agente."""

from __future__ import annotations


def resolve_kb_allow_internet(agent_config: dict) -> bool:
    """
    NULL en agent_config.kb_allow_internet_search → hereda de empresa.
    Si el agente define true/false, ese valor prevalece.
    """
    agent_val = agent_config.get("kb_allow_internet_search")
    if agent_val is not None:
        return bool(agent_val)
    return bool(agent_config.get("empresa_kb_allow_internet_search", False))
