"""Fusión RRF de resultados vectoriales y por palabras clave (BM25 proxy)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Final

_RRF_K: Final[int] = 60


def _normalize_for_match(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in folded if not unicodedata.combining(ch))


@dataclass(frozen=True, slots=True)
class KnowledgeChunk:
    id: int
    titulo: str
    contenido: str
    similarity: float = 0.0
    keyword_score: float = 0.0
    rrf_score: float = 0.0
    sources: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "titulo": self.titulo,
            "contenido": self.contenido,
            "similarity": self.similarity,
            "keyword_score": self.keyword_score,
            "rrf_score": self.rrf_score,
            "sources": list(self.sources),
        }


def _normalize_token(token: str) -> str:
    folded = unicodedata.normalize("NFKD", token.lower())
    return "".join(ch for ch in folded if not unicodedata.combining(ch))


def tokenize_query(query: str) -> list[str]:
    tokens = re.findall(r"[\wáéíóúñü]+", query.lower(), flags=re.UNICODE)
    return [_normalize_token(t) for t in tokens if len(t) >= 2]


def _chunk_from_row(row: dict[str, Any], *, source: str) -> KnowledgeChunk:
    return KnowledgeChunk(
        id=int(row["id"]),
        titulo=str(row.get("titulo") or ""),
        contenido=str(row.get("contenido") or ""),
        similarity=float(row.get("similarity") or 0.0),
        keyword_score=float(row.get("keyword_score") or 0.0),
        sources=(source,),
    )


def reciprocal_rank_fusion(
    ranked_lists: list[list[dict[str, Any]]],
    *,
    list_labels: list[str] | None = None,
) -> list[KnowledgeChunk]:
    """
    Combina listas ordenadas con Reciprocal Rank Fusion (k=60).
    Cada fila debe incluir al menos ``id``, ``titulo``, ``contenido``.
    """
    if not ranked_lists:
        return []

    labels = list_labels or [f"list_{i}" for i in range(len(ranked_lists))]
    merged: dict[int, KnowledgeChunk] = {}
    rrf_scores: dict[int, float] = {}

    for label, rows in zip(labels, ranked_lists):
        for rank, row in enumerate(rows, start=1):
            chunk_id = int(row["id"])
            rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0.0) + (1.0 / (_RRF_K + rank))

            if chunk_id not in merged:
                merged[chunk_id] = _chunk_from_row(row, source=label)
                continue

            existing = merged[chunk_id]
            sources = tuple(dict.fromkeys((*existing.sources, label)))
            merged[chunk_id] = KnowledgeChunk(
                id=existing.id,
                titulo=existing.titulo or str(row.get("titulo") or ""),
                contenido=existing.contenido or str(row.get("contenido") or ""),
                similarity=max(existing.similarity, float(row.get("similarity") or 0.0)),
                keyword_score=max(existing.keyword_score, float(row.get("keyword_score") or 0.0)),
                sources=sources,
            )

    fused: list[KnowledgeChunk] = []
    for chunk_id, chunk in merged.items():
        fused.append(
            KnowledgeChunk(
                id=chunk.id,
                titulo=chunk.titulo,
                contenido=chunk.contenido,
                similarity=chunk.similarity,
                keyword_score=chunk.keyword_score,
                rrf_score=rrf_scores.get(chunk_id, 0.0),
                sources=chunk.sources,
            )
        )

    fused.sort(key=lambda item: item.rrf_score, reverse=True)
    return fused
