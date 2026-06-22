"""Escapado de valores para filtros PostgREST (.or_, ilike)."""


def escape_postgrest_ilike(value: str, *, max_length: int = 100) -> str:
    """Escapa wildcards LIKE y separadores de filtros PostgREST."""
    trimmed = (value or "")[:max_length]
    return (
        trimmed.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
        .replace(",", "")
    )
