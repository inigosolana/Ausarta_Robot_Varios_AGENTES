from services.call_results_service import (
    build_agent_results,
    build_encuesta_results_update,
    legacy_columns_from_agent_results,
    merge_agent_results,
    normalize_agent_type,
)


def test_build_agent_results_encuesta_numerica():
    result = build_agent_results(
        "ENCUESTA_NUMERICA",
        nota_comercial=9,
        nota_instalador=8,
        nota_rapidez=10,
        comentarios="Muy bien",
        datos_extra={"motivo_contratacion": "precio"},
    )
    assert result["scores"]["comercial"] == 9
    assert result["scores"]["instalador"] == 8
    assert result["scores"]["rapidez"] == 10
    assert result["notes"]["comentarios"] == "Muy bien"
    assert result["extracted"]["motivo_contratacion"] == "precio"


def test_build_agent_results_soporte():
    result = build_agent_results(
        "SOPORTE_CLIENTE",
        datos_extra={
            "motivo_llamada": "Factura incorrecta",
            "resolucion": "Reenviada factura corregida",
            "puntos_clave": ["cliente satisfecho"],
        },
    )
    assert result["notes"]["motivo_llamada"] == "Factura incorrecta"
    assert result["notes"]["resolucion"] == "Reenviada factura corregida"


def test_merge_agent_results():
    merged = merge_agent_results(
        {"scores": {"comercial": 7}, "schema_version": 1},
        {"scores": {"rapidez": 9}, "notes": {"comentarios": "ok"}},
    )
    assert merged["scores"]["comercial"] == 7
    assert merged["scores"]["rapidez"] == 9
    assert merged["notes"]["comentarios"] == "ok"


def test_build_encuesta_results_update_syncs_legacy():
    update = build_encuesta_results_update(
        agent_type="ENCUESTA_NUMERICA",
        nota_comercial=8,
        nota_instalador=7,
        nota_rapidez=9,
        comentarios="Todo correcto",
    )
    assert update["puntuacion_comercial"] == 8
    assert update["puntuacion_instalador"] == 7
    assert update["puntuacion_rapidez"] == 9
    assert update["comentarios"] == "Todo correcto"
    assert update["agent_type"] == "ENCUESTA_NUMERICA"
    assert update["agent_results"]["scores"]["comercial"] == 8


def test_normalize_agent_type_default():
    assert normalize_agent_type(None) == "ENCUESTA_NUMERICA"
    assert normalize_agent_type("cualificacion_lead") == "CUALIFICACION_LEAD"


def test_legacy_columns_from_agent_results_empty():
    assert legacy_columns_from_agent_results(None) == {}
