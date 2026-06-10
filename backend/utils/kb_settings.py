"""Resolución de configuración KB / internet por empresa y agente."""

from __future__ import annotations


def resolve_kb_allow_internet(agent_config: dict) -> bool:
    """
    Internet solo si la empresa lo permite Y el agente lo tiene activado.
    La empresa se configura en Base de Conocimiento; el agente elige solo KB o KB+internet.
    """
    company_allows = bool(agent_config.get("empresa_kb_allow_internet_search", False))
    agent_wants = bool(agent_config.get("kb_allow_internet_search", False))
    return company_allows and agent_wants
