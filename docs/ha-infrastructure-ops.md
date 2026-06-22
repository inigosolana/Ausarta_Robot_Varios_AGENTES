# Infraestructura HA y escalabilidad — Operación

**Versión:** 1.0  
**Última actualización:** 2026-06  
**Commits de referencia:** `3d5a99d` (circuit breaker) · `518cc06` (KEDA) · *(Kamailio multi-región — este documento)*

---

## Resumen

Paquete de alta disponibilidad para Ausarta Voice Agent API v2:

| # | Feature | Estado |
|---|---------|--------|
| 1 | Circuit Breaker (Groq, Cartesia, Deepgram) | ✅ `main` |
| 2 | Auto-scaling KEDA (workers ARQ) | ✅ manifiestos `deploy/k8s/` |
| 3 | Multi-región Kamailio (Edge SIP) | ✅ `deploy/kamailio/` |

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

## 3. Multi-región Kamailio (Edge SIP)

### Arquitectura

```
Carrier SIP (Yeastar/CITELIA)
        │
        ▼ :5060/:5061
  Kamailio Edge (kamailio-edge)
        │
        ├─ ipops carrier_latam? → region=latam → Edge-Latam
        └─ default              → region=eu    → Edge-Madrid
        │
        ▼ dispatcher set 1 (peso + probing OPTIONS cada 30s)
  LiveKit SIP nodes
        │
        └─ failover: ds_next_dst() si 408/5xx/503
```

### Enrutamiento por región

| Origen INVITE | Región dispatcher | Nodo preferido |
|---------------|-------------------|----------------|
| IP en `region_peers.list` / `SIP_LATAM_CIDRS` | `latam` | Edge-Latam |
| Resto de carriers trusted | `eu` | Edge-Madrid |

Si el nodo regional está **INACTIVE** (probing fallido), Kamailio selecciona automáticamente cualquier destino activo del set (failover cross-región).

### Balanceo por peso

En `dispatcher.list` el campo **priority** actúa como peso (`modparam dispatcher flags=2`):

| Nodo | Peso default | attrs |
|------|--------------|-------|
| Edge-Madrid primary | 80 | `region=eu;site=edge-madrid;role=primary` |
| Edge-Latam primary | 70 | `region=latam;site=edge-latam;role=primary` |
| Edge-Madrid backup | 40 | `region=eu;site=edge-madrid;role=backup` |

Ajustar pesos según capacidad y latencia medida (RTT) entre edge y LiveKit.

### Failover en llamada activa

1. **Probing:** OPTIONS cada 30 s; 2 fallos → destino INACTIVE.
2. **INVITE en vuelo:** `failure_route[LIVEKIT_FAILOVER]` ante `408`, `503` o `5xx` marca destino y ejecuta `ds_next_dst()`.
3. **Sin destinos:** respuesta `503 Service Unavailable` al carrier.

### Variables de entorno (Easypanel)

```bash
LIVEKIT_EDGE_MADRID_HOST=livekit-eu.ausarta.net
LIVEKIT_EDGE_LATAM_HOST=livekit-latam.ausarta.net
LIVEKIT_EDGE_MADRID_BACKUP_HOST=livekit-eu-2.ausarta.net   # opcional
LIVEKIT_EDGE_MADRID_WEIGHT=80
LIVEKIT_EDGE_LATAM_WEIGHT=70
SIP_LATAM_CIDRS=181.0.0.0/8,200.0.0.0/8
SIP_TRUSTED_CIDRS=203.0.113.10/32
```

`entrypoint.sh` genera `/etc/kamailio/dispatcher.list` al arranque vía `render_dispatcher.sh`. Sin `LIVEKIT_EDGE_*`, usa la plantilla `dispatcher.list.example`.

### Despliegue

```bash
# Desde la raíz del repo
docker compose -f deploy/kamailio/docker-compose.kamailio.yml up -d

# Ver destinos dispatcher
docker exec kamailio-sip-edge kamcmd dispatcher.list

# Forzar reload tras cambiar env
docker compose -f deploy/kamailio/docker-compose.kamailio.yml up -d --force-recreate
```

### Archivos

| Archivo | Función |
|---------|---------|
| `kamailio.cfg` | Rutas LIVEKIT_REGION, LIVEKIT_DISPATCH, LIVEKIT_FAILOVER |
| `dispatcher.list` | Plantilla estática de nodos |
| `region_peers.list` | CIDRs → grupo ipops `carrier_latam` |
| `trusted_peers.list` | Carriers autorizados |
| `render_dispatcher.sh` | Genera dispatcher desde env |
| `entrypoint.sh` | Carga ipops + dispatcher + arranque |

### Checklist staging

- [ ] Certificados TLS en `deploy/kamailio/certs/` (`cert.pem`, `key.pem`)
- [ ] `trusted_peers.list` con IPs reales del carrier
- [ ] `region_peers.list` o `SIP_LATAM_CIDRS` con rangos Latam
- [ ] `LIVEKIT_EDGE_MADRID_HOST` y `LIVEKIT_EDGE_LATAM_HOST` apuntan a livekit-sip reales
- [ ] `kamcmd dispatcher.list` muestra nodos `Active`
- [ ] INVITE de prueba desde EU → log `region=eu`
- [ ] Simular caída nodo (firewall) → log `failover` y llamada completa en nodo backup

### Troubleshooting

| Síntoma | Causa probable |
|---------|----------------|
| `403 Forbidden - Untrusted Source` | IP carrier no en `trusted_peers.list` |
| `503` sin failover | Todos los nodos INACTIVE; revisar conectividad SIP :5060 |
| Siempre `region=eu` | Carrier Latam sin entrada en `region_peers.list` |
| dispatcher.list vacío | `render_dispatcher.sh` sin permisos o sin env/plantilla |
