# Paquete Observabilidad y Rentabilidad — Operación

**Versión:** 1.0  
**Última actualización:** 2026-06

---

## Resumen

| # | Feature | Estado |
|---|---------|--------|
| 1 | OpenTelemetry (trazas distribuidas) | ✅ `d473391` |
| 2 | Rentabilidad Redis + hard limits EUR | ✅ este documento |
| 3 | Customer Anger Score + alertas urgentes | ✅ este documento |

---

## 1. OpenTelemetry

Ver commit `d473391` y variables en `.env.example`:

```bash
OTEL_ENABLED=true
OTEL_SERVICE_NAME=ausarta-voice-api
OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317
```

Verificación: `cd backend && PYTHONPATH=. .venv/bin/python scripts/verify_ha_staging.py` (incluye tracing si se amplía).

---

## 2. Panel de rentabilidad (Redis + hard limits)

### Arquitectura

```
Llamada activa → UsageCollector LiveKit
        │
        ▼ post_call_processor
record_call_usage_billing()
        │
        ├─ Redis HASH ausarta:billing:tenant:{id}:{YYYY-MM}
        │     llm:prompt_tokens / llm:completion_tokens
        │     tts:characters
        │     stt:audio_seconds      ← Deepgram/Cartesia (audio procesado)
        │     telephony:seconds      ← minutos SIP
        │     cost:eur_micro         ← gasto EUR tiempo real (µ€)
        │
        └─ Supabase tenant_usage_events + tenant_usage_monthly (async)

Inicio llamada → enforce_tenant_spending_limit() → HTTP 402 si supera tope
```

### Contadores Redis (tiempo real)

| Campo HASH | Unidad | Origen |
|------------|--------|--------|
| `llm:prompt_tokens` | tokens | Groq/OpenAI vía LiveKit |
| `llm:completion_tokens` | tokens | idem |
| `tts:characters` | caracteres | Cartesia/OpenAI TTS |
| `stt:audio_seconds` | segundos audio | Deepgram/Whisper STT |
| `telephony:seconds` | segundos | duración llamada SIP |
| `cost:eur_micro` | micro-euros | tarifas `BILLING_*_EUR_*` |

### Hard limit (402)

- Columna `empresas.monthly_spend_limit_eur` (migración `20260627_empresa_monthly_spend_limit.sql`)
- `BILLING_SPEND_LIMITS_ENABLED=true`
- Verificación en:
  - `POST /api/calls/outbound`
  - `POST /api/telephony/test-outbound`
  - Drip campañas (`campaigns.py`, `campaign_orchestrator.py`)

```python
from middleware.tenant_context import assert_tenant_within_spending_limit
await assert_tenant_within_spending_limit(empresa_id)  # → HTTP 402
```

### API dashboard B2B

- `GET /api/usage/mi-consumo` — consumo del tenant autenticado
- `GET /api/usage/unit-economics` — desglose EUR (admin)

### Migraciones Supabase

Aplicar en orden:

1. `20260626_tenant_usage_billing.sql`
2. `20260627_empresa_monthly_spend_limit.sql`
3. `20260628_stt_billing.sql` — categoría `stt_audio_seconds`

### Variables tarifas

```bash
BILLING_LLM_INPUT_EUR_PER_1M=0.59
BILLING_LLM_OUTPUT_EUR_PER_1M=0.79
BILLING_TTS_EUR_PER_1K_CHARS=0.015
BILLING_STT_EUR_PER_MINUTE=0.0043
BILLING_TELEPHONY_EUR_PER_MINUTE=0.02
BILLING_SPEND_LIMITS_ENABLED=true
```

### Tests

```bash
cd backend && PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_billing_service.py \
  tests/test_billing_limits_service.py \
  tests/test_call_results_billing.py \
  tests/test_usage_unit_economics.py -q
```

---

## 3. Customer Anger Score (ira del cliente)

### Flujo

```
finalize_call_session()
        │
        ├─ Transcripción cruda (sin PII)
        │
        ├─ asyncio.gather:
        │     analyze_customer_anger()     ← Groq 8B (~400 ms)
        │     analyze_call_disposition()   ← Groq 70B (disposición + datos_extra)
        │
        ├─ merge_anger_into_datos_extra()
        ├─ prepare_transcription_for_storage()  ← PII después del análisis
        └─ enqueue_guardar_encuesta → agent_results.analysis
```

### Campos persistidos

En `datos_extra` y `agent_results.analysis`:

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `customer_anger_score` | int 1–10 | Nivel de enfado del cliente |
| `requires_urgent_human_attention` | bool | Alerta roja B2B |
| `anger_signals` | string[] | Señales detectadas (máx. 5) |

No requiere migración SQL: se guarda en JSONB `encuestas.agent_results`.

### Alertas

- **Frontend:** badge rojo en `ResultsView` si `requires_urgent_human_attention`
- **Telegram:** `maybe_enqueue_urgent_anger_alert()` vía ARQ (`CUSTOMER_ANGER_TELEGRAM_ALERTS=true`)

### Variables

```bash
CUSTOMER_ANGER_ANALYSIS_ENABLED=true
CUSTOMER_ANGER_MODEL=llama-3.1-8b-instant
CUSTOMER_ANGER_TIMEOUT_MS=400
CUSTOMER_ANGER_URGENT_THRESHOLD=8
CUSTOMER_ANGER_TELEGRAM_ALERTS=true
```

### Tests

```bash
cd backend && PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_customer_anger_service.py \
  tests/test_post_call_processor.py \
  tests/test_call_results_service.py -q
```
