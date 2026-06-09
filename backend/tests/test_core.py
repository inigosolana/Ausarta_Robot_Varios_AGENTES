import pytest

from agents.text_utils import _detect_language, _normalize_goodbye_message, anonymize_text
from utils.workflow_state import WorkflowStateMachine, _safe_eval_condition


@pytest.mark.asyncio
async def test_workflow_advance_default_node():
    sm = WorkflowStateMachine(
        [
            {"id": "start", "type": "message", "next_default": "ask", "conditions": []},
            {"id": "ask", "type": "message", "next_default": None, "conditions": []},
        ]
    )
    next_step = sm.advance()
    assert next_step["id"] == "ask"


@pytest.mark.asyncio
async def test_workflow_advance_condition_match():
    sm = WorkflowStateMachine(
        [
            {
                "id": "start",
                "type": "question",
                "variable": "respuesta",
                "next_default": "no",
                "conditions": [{"expr": "respuesta == 'sí'", "target": "si"}],
            },
            {"id": "si", "type": "message", "next_default": None, "conditions": []},
            {"id": "no", "type": "message", "next_default": None, "conditions": []},
        ]
    )
    sm.set_variable("respuesta", "sí")
    next_step = sm.advance("sí")
    assert next_step["id"] == "si"


@pytest.mark.asyncio
async def test_workflow_rejects_dangerous_pattern():
    sm = WorkflowStateMachine(
        [
            {
                "id": "start",
                "type": "question",
                "next_default": "safe",
                "conditions": [{"expr": "__import__('os').system('rm -rf /')", "target": "bad"}],
            },
            {"id": "safe", "type": "message", "next_default": None, "conditions": []},
            {"id": "bad", "type": "message", "next_default": None, "conditions": []},
        ]
    )
    next_step = sm.advance("hola")
    assert next_step["id"] == "safe"


@pytest.mark.asyncio
async def test_workflow_finishes_on_end_node():
    sm = WorkflowStateMachine(
        [
            {"id": "start", "type": "message", "next_default": "end", "conditions": []},
            {"id": "end", "type": "end", "next_default": None, "conditions": []},
        ]
    )
    next_step = sm.advance()
    assert next_step["id"] == "end"
    assert sm.is_finished() is True


@pytest.mark.asyncio
async def test_workflow_set_and_get_variables():
    sm = WorkflowStateMachine([{"id": "start", "type": "message", "next_default": None, "conditions": []}])
    sm.set_variable("nombre", "Ana")
    assert sm.get_variables() == {"nombre": "Ana"}


def test_anonymize_email():
    assert "[REDACTED_EMAIL]" in anonymize_text("Escribe a hola@ausarta.net")


def test_anonymize_spanish_phone():
    assert "[REDACTED_PHONE]" in anonymize_text("Mi telefono es +34 612 34 56 78")


def test_anonymize_nif():
    assert "[REDACTED_DOC]" in anonymize_text("Mi NIF es 12345678Z")


def test_anonymize_empty_text():
    assert anonymize_text("") == ""


def test_detect_language_en():
    assert _detect_language("Hello, how are you") == "en"


def test_detect_language_fr():
    assert _detect_language("Bonjour, comment ça va") == "fr"


def test_detect_language_unknown():
    assert _detect_language("xyz qwr plm") is None


def test_normalize_goodbye_long_message():
    assert _normalize_goodbye_message("Muchas gracias por su tiempo y por toda la información compartida hoy").count(" ") < 8


def test_normalize_goodbye_adds_farewell():
    assert _normalize_goodbye_message("Muchas gracias") == "Muchas gracias. Hasta luego."


def test_normalize_goodbye_empty():
    assert _normalize_goodbye_message("") == "Muchas gracias. Hasta luego."


def test_safe_eval_condition_rejects_dangerous_expression():
    assert _safe_eval_condition("__import__('os').system('rm -rf')", {}) is False
