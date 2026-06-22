#!/usr/bin/env python3
"""
Verificación del Paquete de IA Avanzada en staging/local.

Uso:
  cd backend && PYTHONPATH=. .venv/bin/python scripts/verify_advanced_ai_staging.py
  cd backend && PYTHONPATH=. .venv/bin/python scripts/verify_advanced_ai_staging.py --supabase --empresa-id 1
"""
from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent


def _ok(name: str, detail: str) -> dict[str, Any]:
    return {"name": name, "ok": True, "detail": detail}


def _fail(name: str, detail: str) -> dict[str, Any]:
    return {"name": name, "ok": False, "detail": detail}


def _warn(name: str, detail: str) -> dict[str, Any]:
    return {"name": name, "ok": True, "warn": True, "detail": detail}


def check_env_vars() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    recommended = {
        "GROQ_API_KEY": "Tier 1 semántico y reranker Groq",
        "OPENAI_API_KEY": "Embeddings KB",
    }
    optional = {
        "SEMANTIC_ROUTING_ENABLED": "default true",
        "PII_SANITIZATION_ENABLED": "default true",
        "RAG_HYBRID_ENABLED": "default true",
        "RAG_RERANKER": "heuristic | groq | none",
    }
    for key, why in recommended.items():
        val = os.getenv(key, "").strip()
        if val:
            checks.append(_ok(f"ENV {key}", f"presente ({why})"))
        else:
            checks.append(_warn(f"ENV {key}", f"AUSENTE — {why} (Tier0/regex sigue operativo)"))

    for key, note in optional.items():
        val = os.getenv(key, "")
        checks.append(_ok(f"ENV {key}", f"{val or '<default>'} ({note})"))
    return checks


def check_semantic_router() -> dict[str, Any]:
    from agents.semantic_routes import NEGATIVE_TRANSFER_CUES, TRANSFER_HUMAN_REGEXES

    text = "quiero hablar con un humano por favor"
    normalized = text.lower().strip()
    if any(cue in normalized for cue in NEGATIVE_TRANSFER_CUES):
        return _fail("Semantic Tier0", "frase negativa detectada incorrectamente")
    if any(pattern.search(normalized) for pattern in TRANSFER_HUMAN_REGEXES):
        return _ok("Semantic Tier0", "regex transfer_human OK")
    return _fail("Semantic Tier0", "ningún patrón coincidió")


def check_pii_sanitizer() -> dict[str, Any]:
    from utils.pii_sanitizer import sanitize_transcription_pii

    raw = "Mi email es test@ejemplo.com y DNI 12345678Z"
    out = sanitize_transcription_pii(raw)
    if "test@ejemplo.com" in out.text or "12345678Z" in out.text:
        return _fail("PII sanitizer", "datos sensibles no redactados")
    if out.redaction_count < 2:
        return _fail("PII sanitizer", f"pocas redacciones: {out.redaction_count}")
    return _ok("PII sanitizer", f"{out.redaction_count} redacciones, engine={out.engine}")


def check_rag_rrf() -> dict[str, Any]:
    from services.rag_hybrid import reciprocal_rank_fusion

    vector = [{"id": 1, "titulo": "A", "contenido": "vec", "similarity": 0.9}]
    keyword = [{"id": 2, "titulo": "B", "contenido": "kw", "keyword_score": 0.8}]
    fused = reciprocal_rank_fusion([vector, keyword], list_labels=["vector", "keyword"])
    if len(fused) != 2:
        return _fail("RAG RRF", f"expected 2 chunks, got {len(fused)}")
    return _ok("RAG RRF", f"fusionó {len(fused)} chunks, top rrf={fused[0].rrf_score:.4f}")


def check_ab_assignment() -> dict[str, Any]:
    from services.campaign_ab_service import assign_ab_variant, pick_ab_variant

    campaign = {
        "id": 999,
        "agent_id": 10,
        "agent_id_b": 20,
        "ab_test_enabled": True,
        "ab_split_ratio": 0.5,
    }
    a_count = sum(
        1 for lid in range(200) if pick_ab_variant(lead_id=lid, campaign_id=999, split_ratio=0.5) == "A"
    )
    if not 60 <= a_count <= 140:
        return _fail("A/B split", f"distribución anómala A={a_count}/200")

    b_assignment = assign_ab_variant({**campaign, "ab_split_ratio": 0.0}, lead_id=1)
    if b_assignment.variant != "B" or b_assignment.agent_id != 20:
        return _fail("A/B assign", f"expected B/20 got {b_assignment}")
    return _ok("A/B assignment", f"split ~50/50 (A={a_count}/200), B mapping OK")


async def check_supabase_keyword_rpc(empresa_id: int) -> dict[str, Any]:
    from services.supabase_service import supabase, sb_query

    if not supabase:
        return _fail("Supabase RPC keyword", "cliente no configurado")

    try:
        result = await sb_query(
            lambda: supabase.rpc(
                "search_knowledge_base_keyword",
                {
                    "p_empresa_id": empresa_id,
                    "p_query": "tarifa",
                    "p_limit": 3,
                },
            ).execute()
        )
        count = len(result.data or [])
        return _ok("Supabase RPC keyword", f"search_knowledge_base_keyword OK ({count} filas)")
    except Exception as exc:
        return _fail("Supabase RPC keyword", str(exc)[:160])


def run_pytest_subset() -> dict[str, Any]:
    tests = [
        "tests/test_semantic_router_service.py",
        "tests/test_pii_sanitizer.py",
        "tests/test_rag_hybrid.py",
        "tests/test_campaign_ab_service.py",
    ]
    t0 = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *tests, "-q"],
        cwd=BACKEND_ROOT,
        env={**os.environ, "PYTHONPATH": str(BACKEND_ROOT)},
        capture_output=True,
        text=True,
    )
    elapsed = time.perf_counter() - t0
    if proc.returncode == 0:
        return _ok("pytest subset", f"passed in {elapsed:.1f}s")
    tail = (proc.stdout + proc.stderr)[-400:]
    return _fail("pytest subset", f"exit {proc.returncode}: {tail}")


def print_report(results: list[dict[str, Any]]) -> int:
    width = max(len(r["name"]) for r in results) + 2
    failed = 0
    warned = 0
    print("\n=== Verificación Paquete IA Avanzada ===\n")
    for row in results:
        if not row["ok"]:
            icon = "FAIL"
            failed += 1
        elif row.get("warn"):
            icon = "WARN"
            warned += 1
        else:
            icon = "OK "
        print(f"  [{icon}] {row['name']:<{width}} {row['detail']}")
    print(f"\nTotal: {len(results) - failed}/{len(results)} OK", end="")
    if warned:
        print(f" ({warned} avisos)", end="")
    print("\n")
    return 1 if failed else 0


async def main_async(args: argparse.Namespace) -> int:
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
    load_dotenv(BACKEND_ROOT / ".env")
    os.environ.setdefault("BRIDGE_SERVER_URL_INTERNAL", "http://localhost:8001")

    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))

    results: list[dict[str, Any]] = []
    results.extend(check_env_vars())

    for fn in (check_semantic_router, check_pii_sanitizer, check_rag_rrf, check_ab_assignment):
        try:
            results.append(fn())
        except Exception as exc:
            results.append(_fail(fn.__name__, str(exc)[:160]))

    if args.supabase:
        try:
            results.append(await check_supabase_keyword_rpc(args.empresa_id))
        except Exception as exc:
            results.append(_fail("Supabase RPC keyword", str(exc)[:160]))

    if not args.skip_pytest:
        results.append(run_pytest_subset())

    return print_report(results)


def main() -> None:
    parser = argparse.ArgumentParser(description="Verifica Paquete IA Avanzada en staging")
    parser.add_argument("--supabase", action="store_true", help="Probar RPC keyword en Supabase")
    parser.add_argument("--empresa-id", type=int, default=1, help="empresa_id para RPC KB")
    parser.add_argument("--skip-pytest", action="store_true", help="Omitir subset pytest")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
