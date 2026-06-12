#!/usr/bin/env python3
"""
Ingesta un archivo JSONL de chunks en knowledge_base (Supabase + embeddings).

Requiere variables de entorno (o .env en desarrollo):
  SUPABASE_URL, SUPABASE_SERVICE_KEY (o SUPABASE_KEY), OPENAI_API_KEY

Uso:
  python scripts/ingest_kb_chunks.py --file data/ausarta_kb_chunks.jsonl
  python scripts/ingest_kb_chunks.py --file data/ausarta_kb_chunks.jsonl --replace-titulo-prefix "Líneas Móviles"
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend" if (ROOT / "backend" / "config.py").exists() else ROOT
sys.path.insert(0, str(BACKEND))

if os.getenv("ENVIRONMENT", "production") == "development":
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")

from services.chunk_builder import chunks_to_kb_rows, parse_jsonl_bytes  # noqa: E402
from services.embedding_service import get_embedding  # noqa: E402
from services.supabase_service import supabase, sb_query  # noqa: E402


async def ingest_jsonl(
    file_path: str,
    *,
    empresa_id: int | None = None,
    dry_run: bool = False,
    batch_size: int = 5,
) -> dict:
    if not supabase:
        raise SystemExit("❌ Supabase no configurado. Revisa SUPABASE_URL y SUPABASE_SERVICE_KEY.")

    content = Path(file_path).read_bytes()
    chunks = parse_jsonl_bytes(content, empresa_id=empresa_id)
    if not chunks:
        raise SystemExit(f"❌ No hay chunks válidos en {file_path}")

    kb_rows = chunks_to_kb_rows(chunks)
    if not kb_rows:
        raise SystemExit("❌ Ningún chunk pasó la validación.")

    eid = empresa_id or int(kb_rows[0]["empresa_id"])
    print(f"📦 {len(kb_rows)} chunks a indexar para empresa_id={eid}")

    if dry_run:
        for row in kb_rows[:5]:
            print(f"  - {row['titulo'][:60]}… ({len(row['contenido'])} chars)")
        if len(kb_rows) > 5:
            print(f"  … y {len(kb_rows) - 5} más")
        return {"dry_run": True, "chunks": len(kb_rows)}

    # Insertamos con embeddings en lotes
    inserted = 0
    with_embedding = 0

    for i in range(0, len(kb_rows), batch_size):
        batch = kb_rows[i : i + batch_size]
        embeddings = await asyncio.gather(
            *[get_embedding(r["contenido"]) for r in batch],
            return_exceptions=True,
        )
        for row, emb in zip(batch, embeddings):
            if isinstance(emb, Exception) or emb is None:
                row["embedding"] = None
            else:
                row["embedding"] = emb
                with_embedding += 1

        res = await sb_query(
            lambda rows=batch: supabase.table("knowledge_base").insert(rows).execute()
        )
        inserted += len(res.data or [])

    print(f"✅ Insertados: {inserted} | Con embedding: {with_embedding}")
    return {"inserted": inserted, "with_embedding": with_embedding, "total": len(kb_rows)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingesta JSONL → knowledge_base")
    parser.add_argument("--file", required=True, help="Ruta al .jsonl")
    parser.add_argument("--empresa_id", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    asyncio.run(ingest_jsonl(args.file, empresa_id=args.empresa_id, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
