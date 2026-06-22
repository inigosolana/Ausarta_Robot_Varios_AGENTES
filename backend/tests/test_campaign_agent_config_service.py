"""Tests para resolución de config de agente en campañas."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from services.campaign_agent_config_service import resolve_agent_config_by_survey


def test_resolve_agent_config_by_survey_without_agent_id():
    mock_supabase = MagicMock()
    survey_chain = MagicMock()
    mock_supabase.table.return_value = survey_chain
    survey_chain.select.return_value = survey_chain
    survey_chain.eq.return_value = survey_chain
    survey_chain.execute.return_value = MagicMock(
        data=[{"agent_id": None, "nombre_cliente": "Ana", "empresa_id": 2, "campaign_id": 9}]
    )

    with patch("services.campaign_agent_config_service.supabase", mock_supabase):
        payload = resolve_agent_config_by_survey(100)

    assert payload["name"] == "Bot"
    assert payload["empresa_id"] == 2
