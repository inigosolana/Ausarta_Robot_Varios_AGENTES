# Unit Economics y Billing — Operación y staging

**Versión:** 1.0  
**Última actualización:** 2026-06  
**Commits de referencia:** `b715c82` (tracking) · `ea4eee7` (interceptores) · `74209c1` (dashboard) · `5242769` (402 limits)

---

## Resumen

Sistema de **control de costes por tenant** (`empresa_id`) para saber cuánto cuesta cada cliente y facturar o limitar su uso.

| # | Componente | Rol |
|---|------------|-----|
| 1 | `billing_service.py` | Acumulación Redis (tiempo real) + Supabase (histórico) |
| 2 | Interceptores post-llamada | Registro automático al colgar (LLM, TTS, telefonía) |
| 3 | `/api/usage/*` | Dashboard B2B con costes desglosados |
| 4 | `billing_limits_service.py` | Cortafuego HTTP 402 si supera tope mensual |

---

## Migraciones Supabase (obligatorias)

Aplicar en staging/prod en este orden:

1. `20260626_tenant_usage_billing.sql` — tablas `tenant_usage_events`, `tenant_usage_monthly`, RPC `upsert_tenant_usage_monthly`
2. `20260627_empresa_monthly_spend_limit.sql` — columna `empresas.monthly_spend_limit_eur`

```sql
-- Verificar tablas
SELECT COUNT(*) FROM tenant_usage_monthly;
SELECT id, nombre, monthly_spend_limit_eur FROM empresas LIMIT 5;
```

---

## Variables de entorno

```bash
# ── Tarifas unitarias (EUR) para cálculo de costes en dashboard ──
BILLING_LLM_INPUT_EUR_PER_1M=0.59
BILLING_LLM_OUTPUT_EUR_PER_1M=0.79
BILLING_TTS_EUR_PER_1K_CHARS=0.015
BILLING_STT_EUR_PER_MINUTE=0.0043      # estimado sobre duración de llamada
BILLING_TELEPHONY_EUR_PER_MINUTE=0.02

# ── Cortafuego financiero ──
BILLING_SPEND_LIMITS_ENABLED=true      # false = desactiva HTTP 402
```

Ajustar tarifas según contratos reales con Groq, Cartesia, Deepgram y carrier SIP.

---

## 1. Seguimiento de consumo (`billing_service`)

### Archivos
- `backend/services/billing_service.py`
- `backend/supabase/migrations/20260626_tenant_usage_billing.sql`

### Métodos públicos
```python
from services.billing_service import get_billing_service

billing = get_billing_service()
await billing.log_llm_tokens(empresa_id, prompt_tokens, completion_tokens, model_name)
await billing.log_tts_characters(empresa_id, chars_count, provider)
await billing.log_telephony_seconds(empresa_id, seconds)
snapshot = await billing.get_tenant_usage_summary(empresa_id, period="2026-06")
```

### Redis (tiempo real)
```
ausarta:billing:tenant:{empresa_id}:{YYYY-MM}           → totales
ausarta:billing:tenant:{empresa_id}:{YYYY-MM}:llm:{model}
ausarta:billing:tenant:{empresa_id}:{YYYY-MM}:tts:{provider}
```

Operaciones atómicas vía script Lua + `HINCRBY` (~1 RTT, sin penalizar latencia de llamada).

### Supabase (histórico)
- **`tenant_usage_events`** — log append-only por evento (auditoría FinOps)
- **`tenant_usage_monthly`** — agregados por categoría/modelo/proveedor
- Idempotencia por encuesta: `ausarta:billing:recorded:encuesta:{id}` en Redis

---

## 2. Registro automático al finalizar llamada

### Archivos
- `backend/agents/post_call_processor.py` → `_record_session_billing_usage()`
- `backend/services/call_results_service.py` → `extract_call_usage_metrics()`, `record_call_usage_billing()`
- `backend/agents/dynamic_agent.py` + `agent_lifecycle.py` → `UsageCollector` LiveKit en `metrics_collected`

### Flujo
```
Llamada activa → LiveKit UsageCollector (tokens LLM, chars TTS)
        ↓
finalize_call_session()
        ↓
record_call_usage_billing() → billing_service → Redis + Supabase
```

Métricas extraídas de LiveKit/Groq/Cartesia vía plugins del agente, no estimaciones por duración.

---

## 3. Dashboard B2B (API)

### Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/api/usage/mi-consumo` | Consumo + costes (compatible con `UsageView.tsx`) |
| GET | `/api/usage/unit-economics` | Alias FinOps (mismo payload) |

Parámetros:
- `?year_month=2026-06` — mes a consultar (default: actual)
- `?empresa_id=N` — solo **superadmin**

### Respuesta (campos clave)
```json
{
  "empresa_id": 1,
  "period": "2026-06",
  "usage": {
    "llm_total_tokens": 17000,
    "tts_characters": 45000,
    "telephony_seconds": 3600
  },
  "costs_eur": {
    "llm": 0.42,
    "voice": 0.85,
    "voice_tts": 0.68,
    "voice_stt": 0.17,
    "telephony": 1.20,
    "total": 2.47
  },
  "costs_breakdown": [
    {"category": "llm", "label": "LLM (Groq/OpenAI)", "amount_eur": 0.42},
    {"category": "voice", "label": "Voz (TTS/STT)", "amount_eur": 0.85},
    {"category": "telephony", "label": "Telefonía (SIP/trunk)", "amount_eur": 1.20}
  ],
  "estimated_cost_eur": 2.47
}
```

### Fuente de datos
- **Mes actual:** Redis (tiempo real), fallback Supabase
- **Meses anteriores:** `tenant_usage_monthly` en Supabase

---

## 4. Cortafuego financiero (HTTP 402)

### Archivos
- `backend/services/billing_limits_service.py`
- `backend/middleware/tenant_context.py` → `assert_tenant_within_spending_limit()`
- `backend/routers/telephony.py` → `_enforce_call_placement_limits()`

### Configuración por empresa
```sql
-- Tope de 150 EUR/mes para empresa 42 (NULL = sin límite)
UPDATE empresas
SET monthly_spend_limit_eur = 150.00
WHERE id = 42;

-- Quitar límite
UPDATE empresas SET monthly_spend_limit_eur = NULL WHERE id = 42;
```

### Dónde se bloquea

| Entrada | Comportamiento si supera tope |
|---------|-------------------------------|
| `POST /api/calls/outbound` | HTTP **402 Payment Required** |
| `POST /api/telephony/test-outbound` | HTTP **402** |
| Campañas drip / orchestrator | Lead → `status=failed`, `error_msg` con motivo |

La verificación de **cuota de llamadas** (`max_llamadas_mes`) sigue devolviendo **403**; el tope de **gasto** devuelve **402**.

### Desactivar temporalmente
```bash
BILLING_SPEND_LIMITS_ENABLED=false
```
Reiniciar backend y workers ARQ.

---

## Configurar un tenant de prueba

```sql
-- Empresa demo con tope bajo para probar 402
UPDATE empresas
SET monthly_spend_limit_eur = 0.01
WHERE id = 1;
```

1. Realizar una llamada de prueba con consumo real.
2. Intentar segunda llamada outbound → debe responder 402.
3. Consultar `GET /api/usage/mi-consumo` → ver `costs_eur.total` vs `limit`.

Restaurar después:
```sql
UPDATE empresas SET monthly_spend_limit_eur = NULL WHERE id = 1;
```

---

## Tests unitarios

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_billing_service.py \
  tests/test_call_results_billing.py \
  tests/test_usage_unit_economics.py \
  tests/test_billing_limits_service.py \
  tests/test_post_call_processor.py -q
```

---

## Checklist pre-producción

- [ ] Migraciones `20260626` y `20260627` aplicadas en Supabase
- [ ] Tarifas `BILLING_*` revisadas con FinOps
- [ ] `monthly_spend_limit_eur` configurado por plan de cliente (o NULL)
- [ ] Llamada de prueba → filas en `tenant_usage_events`
- [ ] `/api/usage/mi-consumo` muestra `costs_breakdown` coherente
- [ ] Empresa con tope bajo → 402 en outbound
- [ ] Worker LiveKit registra métricas (`UsageCollector` activo en logs post-llamada)

---

## Rollback rápido

| Feature | Desactivar |
|---------|------------|
| Registro de consumo | No desactivar sin redeploy (pasivo en post-call) |
| Dashboard costes | Endpoint sigue; tarifas a 0 en env si hace falta |
| HTTP 402 | `BILLING_SPEND_LIMITS_ENABLED=false` o `monthly_spend_limit_eur = NULL` |

---

## Logs y soporte

| Componente | Prefijo / mensaje |
|------------|-------------------|
| Billing registro | `[job_id] Billing registrado empresa=` |
| Límite 402 | `[billing-limit] Empresa X bloqueada` |
| Drip bloqueado | `[Drip] Lead X bloqueado por límite de gasto` |

Para incidencias: `empresa_id`, `period` (YYYY-MM), `encuesta_id`, respuesta JSON del 402.

---

## Relación con otros límites SaaS

| Límite | Campo / servicio | HTTP |
|--------|------------------|------|
| Llamadas/mes | `empresas.max_llamadas_mes` | 403 |
| Gasto/mes EUR | `empresas.monthly_spend_limit_eur` | 402 |
| Rate limit API | `empresa_limits.rpm` | 429 |

Ambos checks de llamadas se ejecutan en `_enforce_call_placement_limits()` antes de emitir outbound.
