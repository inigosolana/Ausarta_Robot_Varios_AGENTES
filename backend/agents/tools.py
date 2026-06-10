from .dynamic_agent import (
    DynamicAgent,
)

consultar_conocimiento = DynamicAgent._tool_consultar_conocimiento
buscar_internet = DynamicAgent._tool_buscar_internet
consultar_cliente = DynamicAgent._tool_consultar_cliente
transferir_a_agente_humano = DynamicAgent._http_tool_transferir_humano
finalizar_llamada = DynamicAgent._http_tool_finalizar_llamada

__all__ = [
    "consultar_conocimiento",
    "buscar_internet",
    "consultar_cliente",
    "transferir_a_agente_humano",
    "finalizar_llamada",
]
