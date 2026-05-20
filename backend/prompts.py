"""
prompts.py — Re-export de textos largos del agente y overrides de idioma.

Las constantes BASE_RULES, HUMAN_STYLE_RULES, HUMANIZATION_PROMPT están definidas
en utils.prompt_builder (compartidas con build_agent_prompt).
"""

from utils.prompt_builder import BASE_RULES, HUMAN_STYLE_RULES, HUMANIZATION_PROMPT

# Mensajes de override para inyectar en el chat context al detectar idioma
_LANG_OVERRIDE_MSGS: dict[str, str] = {
    "en": (
        "CRITICAL LANGUAGE OVERRIDE: The caller is speaking ENGLISH. "
        "From this point on you MUST respond EXCLUSIVELY in English. "
        "Switch your entire script, greeting, and questions to English immediately."
    ),
    "fr": (
        "CHANGEMENT DE LANGUE CRITIQUE : Le client parle FRANÇAIS. "
        "À partir de maintenant, répondez EXCLUSIVEMENT en français. "
        "Traduisez votre script et vos questions en français immédiatement."
    ),
    "de": (
        "KRITISCHER SPRACHENWECHSEL: Der Anrufer spricht DEUTSCH. "
        "Ab sofort antworten Sie AUSSCHLIESSLICH auf Deutsch. "
        "Übersetzen Sie Ihr Skript und Ihre Fragen sofort ins Deutsche."
    ),
    "it": (
        "CAMBIO LINGUA CRITICO: Il chiamante parla ITALIANO. "
        "Da questo momento in poi rispondere ESCLUSIVAMENTE in italiano. "
        "Traducete immediatamente il vostro script e le vostre domande in italiano."
    ),
    "pt": (
        "MUDANÇA DE IDIOMA CRÍTICA: O chamador fala PORTUGUÊS. "
        "A partir de agora responda EXCLUSIVAMENTE em português. "
        "Traduza imediatamente o seu guião e perguntas para português."
    ),
}
