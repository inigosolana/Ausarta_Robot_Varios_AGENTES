"""
chunk_builder.py — Normaliza documentos a chunks semánticos (1 producto = 1 chunk).

Formato interno estándar antes de embeddings:
  {id, empresa_id, agent_id, categoria, titulo, contenido, pvp, tags, fuente, activo}
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any


def make_chunk_id(empresa_id: int, row_id: Any, nombre: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(nombre).lower())[:40].strip("_")
    return f"emp{empresa_id}_svc{row_id}_{slug}"


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        f = float(value)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def build_contenido_from_service_row(row: dict[str, Any]) -> str:
    """Construye el texto del chunk a partir de una fila del Excel de servicios."""
    nombre = str(row.get("Nombre") or "").strip()
    if not nombre:
        return ""

    parts = [f"{nombre}:"]

    info = row.get("Información comercial") or row.get("InformaciÃ³n comercial") or ""
    if info:
        parts.append(str(info).strip())

    desc = row.get("Descripción contractual") or row.get("DescripciÃ³n contractual") or ""
    if desc and str(desc).strip() not in str(info):
        parts.append(str(desc).strip())

    pvp = _safe_float(row.get("PVP recomendado"))
    if pvp:
        parts.append(f"PVP recomendado {pvp}€/mes.")

    pmin = _safe_float(row.get("Precio venta mínimo") or row.get("Precio venta minimo"))
    if pmin:
        parts.append(f"Precio mínimo de venta {pmin}€/mes.")

    coste = _safe_float(row.get("Precio coste"))
    if coste:
        parts.append(f"Precio coste {coste}€/mes.")

    ofertable = str(row.get("Ofertable") or "").strip().lower()
    activable = str(row.get("Activable") or "").strip().lower()
    if ofertable in {"sí", "si", "s"}:
        parts.append("Producto ofertable y comercializable.")
    if activable in {"no", "n"}:
        parts.append("Actualmente no activable.")

    tipo = row.get("Tipo de servicio")
    if tipo:
        parts.append(f"Tipo: {tipo}.")

    return " ".join(p for p in parts if p).strip()


def build_tags_from_service_row(row: dict[str, Any]) -> list[str]:
    familia = str(row.get("familia") or row.get("Familia") or "").strip()
    tags: list[str] = []
    if familia:
        tags.append(familia.lower().replace(" ", "_"))

    nombre = str(row.get("Nombre") or "").lower()
    for keyword in (
        "fibra", "4g", "movil", "móvil", "centralita", "licencia",
        "firewall", "m2m", "bono", "router", "lpd", "nas", "ilimitada",
    ):
        if keyword in nombre:
            tags.append(keyword.replace("ó", "o"))

    gb_match = re.search(r"(\d+)\s*gb", nombre, re.IGNORECASE)
    if gb_match:
        tags.append(f"{gb_match.group(1)}gb")

    return list(dict.fromkeys(tags))


def service_row_to_chunk(
    row: dict[str, Any],
    *,
    empresa_id: int,
    agent_id: int | None = None,
    fuente: str = "services_excel",
    fecha_ingesta: str | None = None,
) -> dict[str, Any] | None:
    """Convierte una fila del Excel de servicios en un chunk estándar."""
    nombre = str(row.get("Nombre") or "").strip()
    if not nombre:
        return None

    contenido = build_contenido_from_service_row(row)
    if len(contenido) < 20:
        return None

    row_id = row.get("ID") or row.get("id") or nombre
    categoria = str(row.get("familia") or row.get("Familia") or "Servicios").strip()

    return {
        "id": make_chunk_id(empresa_id, row_id, nombre),
        "empresa_id": empresa_id,
        "agent_id": agent_id,
        "categoria": categoria,
        "titulo": nombre,
        "contenido": contenido,
        "pvp": _safe_float(row.get("PVP recomendado")),
        "tags": build_tags_from_service_row(row),
        "fuente": fuente,
        "fecha_ingesta": fecha_ingesta or date.today().isoformat(),
        "activo": True,
        "source_type": "services_excel",
    }


def chunks_to_kb_rows(
    chunks: list[dict[str, Any]],
    *,
    default_titulo: str = "Catálogo servicios",
) -> list[dict[str, Any]]:
    """
    Convierte chunks estándar en filas listas para insertar en knowledge_base.
    Cada chunk = una fila (sin re-chunking por tokens).
    """
    rows: list[dict[str, Any]] = []
    for idx, chunk in enumerate(chunks):
        if chunk.get("activo") is False:
            continue
        contenido = str(chunk.get("contenido") or "").strip()
        if not contenido:
            continue
        titulo = str(chunk.get("titulo") or default_titulo).strip()
        categoria = str(chunk.get("categoria") or "").strip()
        if categoria and categoria.lower() not in titulo.lower():
            titulo = f"{categoria} - {titulo}"

        row: dict[str, Any] = {
            "empresa_id": int(chunk["empresa_id"]),
            "titulo": titulo,
            "contenido": contenido,
            "chunk_index": idx,
            "source_type": str(chunk.get("source_type") or "jsonl"),
        }
        agent_id = chunk.get("agent_id")
        if agent_id is not None:
            row["agent_id"] = int(agent_id)
        rows.append(row)
    return rows


def parse_jsonl_bytes(content: bytes, empresa_id: int | None = None) -> list[dict[str, Any]]:
    """Parsea un archivo JSONL a lista de chunks estándar."""
    text = content.decode("utf-8", errors="replace")
    chunks: list[dict[str, Any]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Línea {line_no} JSON inválido: {exc}") from exc
        if not isinstance(obj, dict):
            continue
        if empresa_id is not None and obj.get("empresa_id") not in (None, empresa_id):
            continue
        if "contenido" not in obj:
            continue
        obj.setdefault("source_type", "jsonl")
        obj.setdefault("activo", True)
        chunks.append(obj)
    return chunks


def write_jsonl(chunks: list[dict[str, Any]], output_path: str | Path) -> int:
    """Escribe chunks a un archivo JSONL. Devuelve el número de líneas escritas."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with open(out, "w", encoding="utf-8") as f:
        for chunk in chunks:
            if chunk.get("activo") is False:
                continue
            if not str(chunk.get("contenido") or "").strip():
                continue
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")
            count += 1
    return count
