"""Tests para nodo schedule del workflow engine."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.workflow_schedule_service import resolve_workflow_template, schedule_workflow_follow_up
from utils.workflow_compiler import compile_workflow_to_prompt


def test_resolve_workflow_template_substitutes_variables_and_context():
    result = resolve_workflow_template(
        "camp-{{campaign_id}}-emp-{{empresa_id}}",
        {"campaign_id": 42},
        {"empresa_id": 7},
    )
    assert result == "camp-42-emp-7"


def test_compile_workflow_includes_schedule_node():
    workflow = {
        "start_node": "n1",
        "nodes": [
            {"id": "n1", "type": "message", "label": "Saludo", "content": "Hola"},
            {
                "id": "n2",
                "type": "schedule",
                "label": "Follow-up",
                "delay_days": 3,
                "campaign_id_ref": "{{campaign_id}}",
            },
            {"id": "n3", "type": "end", "label": "Fin"},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n2"},
            {"id": "e2", "source": "n2", "target": "n3"},
        ],
    }
    prompt, steps = compile_workflow_to_prompt(workflow, "workflow", "")
    assert "seguimiento en 3 día(s)" in prompt
    schedule_step = next(s for s in steps if s["type"] == "schedule")
    assert schedule_step["delay_days"] == 3
    assert schedule_step["campaign_id_ref"] == "{{campaign_id}}"


@pytest.mark.asyncio
async def test_schedule_workflow_follow_up_updates_existing_lead():
    mock_supabase = MagicMock()
    table_mock = MagicMock()
    mock_supabase.table.return_value = table_mock

    update_chain = MagicMock()
    update_chain.eq.return_value.execute = MagicMock()
    table_mock.update.return_value = update_chain

    with (
        patch("services.workflow_schedule_service.supabase", mock_supabase),
        patch(
            "services.campaign_locks.enqueue_scheduler_tick",
            new_callable=AsyncMock,
        ) as mock_tick,
    ):
        result = await schedule_workflow_follow_up(
            survey_id=100,
            empresa_id=1,
            campaign_id_ref="55",
            lead_id=999,
            delay_days=2,
        )

    assert result["ok"] is True
    assert result["lead_id"] == 999
    assert result["campaign_id"] == 55
    mock_tick.assert_awaited_once()
    table_mock.update.assert_called()

@pytest.mark.asyncio
async def test_schedule_workflow_follow_up_unresolved_campaign():
    with patch("services.workflow_schedule_service.supabase", MagicMock()):
        result = await schedule_workflow_follow_up(
            survey_id=0,
            empresa_id=1,
            campaign_id_ref="{{missing}}",
            lead_id=None,
            delay_days=1,
            call_context={},
        )
    assert result["ok"] is False
    assert result["error"] == "campaign_id_unresolved"
