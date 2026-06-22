# Infraestructura HA y escalabilidad — Operación

**Versión:** 1.0  
**Última actualización:** 2026-06  
**Commits de referencia:** `3d5a99d` (circuit breaker) · *(KEDA — este documento)*

---

## Resumen

Paquete de alta disponibilidad para Ausarta Voice Agent API v2:

| # | Feature | Estado |
|---|---------|--------|
| 1 | Circuit Breaker (Groq, Cartesia, Deepgram) | ✅ `main` |
| 2 | Auto-scaling KEDA (workers ARQ) | ✅ manifiestos `deploy/k8s/` |
| 3 | Multi-región Kamailio (Edge SIP) | ⏳ pendiente |

---

## 1. Circuit Breaker

Ver commit `3d5a99d`. Variables:

```bash
CIRCUIT_BREAKER_FAILURE_THRESHOLD=3
CIRCUIT_BREAKER_OPEN_SECONDS=300
CIRCUIT_BREAKER_EXTREME_TIMEOUT_SECONDS=15
CIRCUIT_BREAKER_USE_REDIS=true
```

Tests: `cd backend && pytest tests/test_circuit_breaker.py -q`

---

## 2. KEDA — Workers ARQ

### Arquitectura

```
API / LiveKit Agent ──enqueue──► Redis ZSET arq:queue
                                        │
                                   KEDA ScaledObject
                                   (ZCARD arq:queue)
                                        │
                                        ▼
                              Deployment arq-worker (1–20 pods)
                                        │
                                   arq worker.WorkerSettings
```

ARQ usa la clave **`arq:queue`** (sorted set). KEDA ≥ 2.13 detecta el tipo y aplica `ZCARD` automáticamente.

### Reglas de escalado

| Condición | Réplicas |
|-----------|----------|
| Cola vacía / baja carga | **1** (`minReplicaCount`) |
| >50 jobs por pod objetivo | Escala hacia arriba (`listLength: 50`) |
| Pico de campañas | Hasta **20** pods (`maxReplicaCount`) |

Ejemplo: 120 jobs en cola → `ceil(120/50) = 3` pods.

### Prerrequisitos en el cluster

1. **KEDA** instalado (`kubectl get crd scaledobjects.keda.sh`).
2. **Redis** accesible desde el namespace (Service `redis` o URL externa).
3. Imagen del backend publicada (misma que `docker-compose` → `backend/Dockerfile`).

```bash
# Instalar KEDA (ejemplo Helm)
helm repo add kedacore https://kedacore.github.io/charts
helm install keda kedacore/keda --namespace keda --create-namespace
```

### Despliegue

```bash
# 1. Secret con credenciales (ver deploy/k8s/secret-example.yaml)
kubectl -n ausarta-voice create secret generic ausarta-backend-secrets \
  --from-literal=REDIS_PASSWORD='...' \
  --from-literal=REDIS_URL='redis://:PASSWORD@redis:6379/0' \
  # ... resto de claves del stack (SUPABASE_*, LIVEKIT_*, etc.)

# 2. Ajustar imagen en kustomization.yaml si aplica
# 3. Aplicar manifiestos
kubectl apply -k deploy/k8s/

# 4. Verificar
kubectl -n ausarta-voice get scaledobject arq-worker-scaler
kubectl -n ausarta-voice get hpa
kubectl -n ausarta-voice get pods -l app.kubernetes.io/name=arq-worker
```

### Validación local (sin cluster)

```bash
kubectl kustomize deploy/k8s/ > /tmp/arq-k8s-rendered.yaml
# Revisar ScaledObject + Deployment
```

### Simular carga en cola (staging)

```python
# Desde shell con REDIS_URL configurado
import asyncio
from arq import create_pool
from arq.connections import RedisSettings
import os

async def main():
    pool = await create_pool(RedisSettings.from_dsn(os.environ["REDIS_URL"]))
    for i in range(60):
        await pool.enqueue_job("campaign_scheduler_task")
    await pool.close()

asyncio.run(main())
```

Tras ~15–30 s, KEDA debería subir réplicas si hay >50 jobs pendientes.

### Ajuste fino

| Parámetro | Ubicación | Default |
|-----------|-----------|---------|
| `listLength` | `arq-worker-scaledobject.yaml` | 50 |
| `maxReplicaCount` | idem | 20 |
| `minReplicaCount` | idem | 1 |
| `pollingInterval` | idem | 15s |
| `cooldownPeriod` | idem | 60s |

### Troubleshooting

| Síntoma | Causa probable |
|---------|----------------|
| ScaledObject `Ready=False` | Redis inaccesible o password incorrecto en `TriggerAuthentication` |
| Siempre 1 pod con cola grande | KEDA no instalado; revisar `kubectl describe scaledobject` |
| Workers no consumen | `REDIS_URL` del Secret distinto al Redis que monitoriza KEDA |
| Health check falla | `arq worker.WorkerSettings --check` requiere Redis y mismo `REDIS_URL` |

---

## 3. Multi-región Kamailio

Pendiente (Punto 3). Archivos base: `deploy/kamailio/kamailio.cfg`, `dispatcher.list`.
