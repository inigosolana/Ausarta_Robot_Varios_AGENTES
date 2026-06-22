#!/usr/bin/env python3
"""
Verificación del Paquete HA (Circuit Breaker + KEDA + Kamailio) en staging/local.

Uso:
  cd backend && PYTHONPATH=. .venv/bin/python scripts/verify_ha_staging.py
  cd backend && PYTHONPATH=. .venv/bin/python scripts/verify_ha_staging.py --redis
  cd backend && PYTHONPATH=. .venv/bin/python scripts/verify_ha_staging.py --kubectl --namespace ausarta-voice
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
K8S_DIR = REPO_ROOT / "deploy" / "k8s"
KAMAILIO_DIR = REPO_ROOT / "deploy" / "kamailio"


def _ok(name: str, detail: str) -> dict[str, Any]:
    return {"name": name, "ok": True, "detail": detail}


def _fail(name: str, detail: str) -> dict[str, Any]:
    return {"name": name, "ok": False, "detail": detail}


def _warn(name: str, detail: str) -> dict[str, Any]:
    return {"name": name, "ok": True, "warn": True, "detail": detail}


def check_circuit_breaker_env(*, require_redis: bool = False) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    keys = {
        "CIRCUIT_BREAKER_FAILURE_THRESHOLD": "3",
        "CIRCUIT_BREAKER_OPEN_SECONDS": "300",
        "CIRCUIT_BREAKER_EXTREME_TIMEOUT_SECONDS": "15",
        "CIRCUIT_BREAKER_USE_REDIS": "true",
        "REDIS_URL": "requerido para breaker distribuido y ARQ",
    }
    for key, default in keys.items():
        val = os.getenv(key, "").strip()
        if val:
            checks.append(_ok(f"ENV {key}", val[:60] + ("…" if len(val) > 60 else "")))
        elif key == "REDIS_URL":
            if require_redis:
                checks.append(_fail(f"ENV {key}", "ausente — breaker y ARQ necesitan Redis"))
            else:
                checks.append(_warn(f"ENV {key}", "ausente — usar --redis para validar cola ARQ"))
        else:
            checks.append(_warn(f"ENV {key}", f"ausente — default {default}"))
    return checks


def check_k8s_manifests() -> list[dict[str, Any]]:
    required = [
        "namespace.yaml",
        "arq-worker-deployment.yaml",
        "arq-worker-scaledobject.yaml",
        "trigger-authentication-redis.yaml",
        "kustomization.yaml",
    ]
    checks: list[dict[str, Any]] = []
    missing = [name for name in required if not (K8S_DIR / name).is_file()]
    if missing:
        checks.append(_fail("K8s manifests", f"faltan: {', '.join(missing)}"))
    else:
        checks.append(_ok("K8s manifests", f"{len(required)} ficheros en deploy/k8s/"))

    scaled = K8S_DIR / "arq-worker-scaledobject.yaml"
    if scaled.is_file():
        text = scaled.read_text()
        for token in ("arq:queue", "minReplicaCount: 1", "maxReplicaCount: 20", 'listLength: "50"'):
            if token not in text:
                checks.append(_fail("KEDA ScaledObject", f"no contiene {token!r}"))
                return checks
        checks.append(_ok("KEDA ScaledObject", "arq:queue, min=1, max=20, threshold=50"))
    return checks


def check_kubectl_kustomize() -> dict[str, Any]:
    proc = subprocess.run(
        ["kubectl", "kustomize", str(K8S_DIR)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout)[-200:]
        return _warn("kubectl kustomize", f"no disponible o error: {err.strip()}")
    if "kind: ScaledObject" not in proc.stdout:
        return _fail("kubectl kustomize", "render sin ScaledObject")
    return _ok("kubectl kustomize", "manifiestos renderizan correctamente")


def check_kubectl_scaledobject(namespace: str) -> dict[str, Any]:
    proc = subprocess.run(
        ["kubectl", "-n", namespace, "get", "scaledobject", "arq-worker-scaler", "-o", "jsonpath={.status.conditions}"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return _warn(
            "KEDA cluster",
            f"ScaledObject no encontrado en ns={namespace} (¿aún no desplegado?)",
        )
    body = proc.stdout.strip()
    if "True" in body and "Ready" in body:
        return _ok("KEDA cluster", f"arq-worker-scaler Ready en {namespace}")
    return _warn("KEDA cluster", f"estado: {body[:120] or 'sin conditions'}")


def check_kamailio_files() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    required = [
        "kamailio.cfg",
        "dispatcher.list",
        "region_peers.list",
        "render_dispatcher.sh",
        "entrypoint.sh",
    ]
    missing = [name for name in required if not (KAMAILIO_DIR / name).is_file()]
    if missing:
        checks.append(_fail("Kamailio files", f"faltan: {', '.join(missing)}"))
        return checks
    checks.append(_ok("Kamailio files", f"{len(required)} ficheros en deploy/kamailio/"))

    cfg = (KAMAILIO_DIR / "kamailio.cfg").read_text()
    for route in ("LIVEKIT_REGION", "LIVEKIT_FAILOVER", "ds_next_dst"):
        if route not in cfg:
            checks.append(_fail("Kamailio routes", f"no encontrado: {route}"))
            return checks
    checks.append(_ok("Kamailio routes", "REGION + FAILOVER + ds_next_dst"))

    render = KAMAILIO_DIR / "render_dispatcher.sh"
    env = {
        **os.environ,
        "LIVEKIT_EDGE_MADRID_HOST": "staging-madrid.test",
        "LIVEKIT_EDGE_LATAM_HOST": "staging-latam.test",
    }
    proc = subprocess.run(
        [str(render)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(KAMAILIO_DIR),
    )
    if proc.returncode != 0:
        checks.append(_fail("render_dispatcher.sh", (proc.stderr or proc.stdout)[-160:]))
    elif "region=eu" in proc.stdout and "region=latam" in proc.stdout:
        checks.append(_ok("render_dispatcher.sh", "genera nodos EU + Latam"))
    else:
        checks.append(_fail("render_dispatcher.sh", "salida sin attrs region"))
    return checks


async def check_redis_arq_queue() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    url = os.getenv("REDIS_URL", "").strip()
    if not url:
        return [_warn("Redis ARQ", "REDIS_URL ausente — omitido")]

    try:
        from arq.connections import RedisSettings, create_pool
    except ImportError as exc:
        return [_fail("Redis ARQ", f"import arq: {exc}")]

    pool = None
    try:
        pool = await create_pool(RedisSettings.from_dsn(url))
        depth = await pool.zcard("arq:queue")
        checks.append(_ok("Redis ARQ", f"ZCARD arq:queue = {depth}"))
        pong = await pool.ping()
        if pong:
            checks.append(_ok("Redis ping", "conexión OK"))
        else:
            checks.append(_fail("Redis ping", "sin respuesta"))
    except Exception as exc:
        checks.append(_fail("Redis ARQ", str(exc)[:160]))
    finally:
        if pool is not None:
            await pool.close()
    return checks


def check_arq_worker_health() -> dict[str, Any]:
    if not os.getenv("REDIS_URL", "").strip():
        return _warn("ARQ --check", "REDIS_URL ausente — omitido")
    proc = subprocess.run(
        [sys.executable, "-m", "arq", "worker.WorkerSettings", "--check"],
        cwd=BACKEND_ROOT,
        env={**os.environ, "PYTHONPATH": str(BACKEND_ROOT)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode == 0:
        return _ok("ARQ --check", "worker.WorkerSettings saludable")
    tail = (proc.stdout + proc.stderr)[-300:]
    return _fail("ARQ --check", f"exit {proc.returncode}: {tail}")


def run_pytest_circuit_breaker() -> dict[str, Any]:
    t0 = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_circuit_breaker.py", "-q"],
        cwd=BACKEND_ROOT,
        env={**os.environ, "PYTHONPATH": str(BACKEND_ROOT)},
        capture_output=True,
        text=True,
    )
    elapsed = time.perf_counter() - t0
    if proc.returncode == 0:
        return _ok("pytest circuit_breaker", f"passed in {elapsed:.1f}s")
    tail = (proc.stdout + proc.stderr)[-400:]
    return _fail("pytest circuit_breaker", f"exit {proc.returncode}: {tail}")


def print_report(results: list[dict[str, Any]]) -> int:
    width = max(len(r["name"]) for r in results) + 2
    failed = 0
    warned = 0
    print("\n=== Verificación Paquete HA (staging) ===\n")
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

    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))

    results: list[dict[str, Any]] = []
    results.extend(check_circuit_breaker_env(require_redis=args.redis))
    results.extend(check_k8s_manifests())
    results.extend(check_kamailio_files())

    if args.kubectl:
        results.append(check_kubectl_kustomize())
        results.append(check_kubectl_scaledobject(args.namespace))

    if args.redis:
        results.extend(await check_redis_arq_queue())
        results.append(check_arq_worker_health())

    if not args.skip_pytest:
        results.append(run_pytest_circuit_breaker())

    return print_report(results)


def main() -> None:
    parser = argparse.ArgumentParser(description="Verifica Paquete HA en staging")
    parser.add_argument("--redis", action="store_true", help="Probar Redis arq:queue y ARQ --check")
    parser.add_argument("--kubectl", action="store_true", help="Validar kustomize y ScaledObject en cluster")
    parser.add_argument("--namespace", default="ausarta-voice", help="Namespace K8s (default: ausarta-voice)")
    parser.add_argument("--skip-pytest", action="store_true", help="Omitir pytest circuit breaker")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
