from __future__ import annotations

import io
import json
from typing import Any


async def parse_services_excel(
    file_bytes: bytes,
    empresa_id: int,
    sheet_name: str = "informe CRM",
) -> list[dict[str, Any]]:
    """Convierte cada fila del Excel en documentos KB orientados a servicios."""
    _ = empresa_id
    try:
        from openpyxl import load_workbook  # type: ignore
    except ImportError:
        return []

    wb = load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    sheet = wb[sheet_name] if sheet_name in wb.sheetnames else wb[wb.sheetnames[0]]
    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        return []

    headers = [str(h or "").strip() for h in rows[0]]
    docs: list[dict[str, Any]] = []
    active_rows = max(0, len(rows) - 1)

    for values in rows[1:]:
        row = {headers[idx]: values[idx] for idx in range(min(len(headers), len(values)))}
        ofertable = str(row.get("Ofertable") or "").strip().lower()
        activable = str(row.get("Activable") or "").strip().lower()
        if ofertable not in {"si", "sí", "s"} and activable not in {"si", "sí", "s"}:
            continue

        uds_activas = row.get("Uds totales activas")
        try:
            uds_activas_num = float(uds_activas or 0)
        except (TypeError, ValueError):
            uds_activas_num = 0
        if active_rows > 50 and uds_activas_num == 0:
            continue

        nombre = str(row.get("Nombre") or "").strip()
        familia = str(row.get("familia") or row.get("Familia") or "").strip()
        if not nombre:
            continue

        titulo = f"{familia} - {nombre}".strip(" -")
        contenido = (
            f"Servicio: {nombre}\n"
            f"Familia: {familia}\n"
            f"Tipo: {row.get('Tipo de servicio') or ''}\n"
            f"Descripcion: {row.get('Descripción contractual') or row.get('DescripciÃ³n contractual') or ''}\n"
            f"Informacion comercial: {row.get('Información comercial') or row.get('InformaciÃ³n comercial') or ''}\n"
            f"Precio coste: {row.get('Precio coste') or ''} EUR/mes\n"
            f"PVP recomendado: {row.get('PVP recomendado') or ''} EUR/mes\n"
            f"Ofertable: {row.get('Ofertable') or ''} | Activable: {row.get('Activable') or ''}\n"
            f"Unidades activas: {row.get('Uds totales activas') or ''}"
        )
        docs.append({"titulo": titulo, "contenido": contenido, "source_type": "services_excel"})

    return docs


async def extract_text_from_docx(file_bytes: bytes) -> str:
    try:
        from docx import Document  # type: ignore
    except ImportError:
        return ""

    doc = Document(io.BytesIO(file_bytes))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


async def normalize_documents_for_preview(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    preview: list[dict[str, Any]] = []
    for doc in documents:
        preview.append(
            {
                "titulo": doc.get("titulo") or "",
                "source_type": doc.get("source_type") or "manual",
                "contenido_preview": str(doc.get("contenido") or "")[:500],
            }
        )
    return preview


def stringify_json_document(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)
