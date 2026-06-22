# Paquete de Funcionalidades Avanzadas de IA — Operación y staging

**Versión:** 1.0  
**Última actualización:** 2026-06  
**Commits de referencia:** `d848d81` (semántico) · `d4c1430` (PII) · `521ba0d` (RAG) · `69ac105` (A/B)

---

## Resumen

Cuatro capacidades desplegadas en `main` para tenants de Ausarta Voice Agent API v2:

| # | Feature | Efecto en producción |
|---|---------|---------------------|
| 1 | Enrutamiento semántico | Transferencia a humano sin pasar por LLM 70B |
| 2 | Sanitización PII | Transcripciones censuradas antes de Supabase (GDPR) |
| 3 | RAG híbrido + re-ranking | KB: vector + keywords → RRF → rerank |
| 4 | A/B testing campañas | Variante A/B de agente, reparto 50/50 por lead |

---

## Variables de entorno

Añadir en `.env` del **backend** y del **worker LiveKit** (agente):

```bash
# ── 1. Enrutamiento semántico ──
SEMANTIC_ROUTING_ENABLED=true
SEMANTIC_ROUTER_MODEL=llama-3.1-8b-instant
SEMANTIC_ROUTER_TIMEOUT_MS=250
SEMANTIC_ROUTER_MIN_CONFIDENCE=0.85
SEMANTIC_ROUTER_TIER0_ONLY=false    # true = solo regex, sin Groq
GROQ_API_KEY=gsk_...                # requerido para Tier 1

# ── 2. PII en transcripciones ──
PII_SANITIZATION_ENABLED=true
PII_SANITIZER_ENGINE=regex          # regex | presidio (opcional)

# ── 3. RAG híbrido ──
RAG_HYBRID_ENABLED=true
RAG_CANDIDATE_MULTIPLIER=3
RAG_VECTOR_FETCH_THRESHOLD=0.55
RAG_RERANKER=heuristic              # heuristic | groq | none
RAG_RERANKER_MODEL=llama-3.1-8b-instant
RAG_RERANKER_TIMEOUT_MS=400
OPENAI_API_KEY=sk-...               # embeddings text-embedding-3-small

# ── 4. A/B campañas ──
# Sin env extra: se configura por campaña en BD/API
```

---

## 1. Enrutamiento semántico

### Archivos
- `backend/services/semantic_router_service.py`
- `backend/agents/dynamic_agent.py` → `on_user_turn_completed` + `StopResponse`
- `backend/agents/semantic_routes.py`

### Flujo
```
STT final → on_user_turn_completed()
  → Tier 0 regex (~0 ms)
  → Tier 1 Groq 8B (timeout 250 ms)
  → transfer_human → session.interrupt() + _execute_human_transfer()
  → StopResponse (no LLM principal)
```

### Config por tenant (agent_config / datos_extra)
```json
{
  "semantic_routing_enabled": true,
  "human_transfer_phrases": ["soporte nivel 2", "departamento comercial"]
}
```

### Verificación en staging
1. Llamada de prueba al agente.
2. Decir: *"Quiero hablar con un humano"* o *"Pásame con un agente"*.
3. En logs del agente (`agent.log` o stdout):
   - `Semantic route transfer_human tier=tier0` o `tier=tier1`
   - `Transferencia encolada ... source=semantic_router`
4. La llamada debe transferir **sin** respuesta larga del LLM previa.

### Desactivar por agente
`semantic_routing_enabled: false` en `datos_extra` del agente.

---

## 2. Sanitización PII (GDPR)

### Archivos
- `backend/utils/pii_sanitizer.py`
- `backend/services/call_results_service.py` → `prepare_transcription_for_storage()`
- Integrado en: `post_call_processor.py`, `telephony.py` `/guardar-encuesta`, snapshots mid-call

### Qué se redacta
| Tipo | Placeholder |
|------|-------------|
| Email | `[REDACTED_EMAIL]` |
| Teléfono | `[REDACTED_PHONE]` |
| DNI/NIE | `[REDACTED_DNI_NIE]` |
| IBAN | `[REDACTED_IBAN]` |
| Tarjeta | `[REDACTED_CREDIT_CARD]` |
| Dirección ES | `[REDACTED_ADDRESS]` |

### Importante
- El **análisis LLM post-llamada** (`analyze_call_disposition`) usa texto **completo en memoria**.
- Lo que se **persiste en Supabase** y webhooks n8n va **sanitizado**.

### Verificación en staging
1. Llamada donde el cliente diga un email o DNI de prueba ficticio.
2. Consultar `encuestas.transcription` en Supabase.
3. Confirmar placeholders `[REDACTED_*]` y ausencia del dato en claro.

```sql
SELECT id, transcription, ab_variant
FROM encuestas
ORDER BY id DESC
LIMIT 5;
```

---

## 3. RAG híbrido + re-ranking

### Archivos
- `backend/services/embedding_service.py` → `search_knowledge()`
- `backend/services/rag_hybrid.py` (RRF)
- `backend/services/reranker_service.py`
- RPC Supabase: `search_knowledge_base` + `search_knowledge_base_keyword`

### Flujo
```
consulta → embedding vectorial (N candidatos)
        → FTS español keyword (N candidatos)
        → RRF fusión (k=60)
        → reranker heurístico o Groq
        → top-K al prompt / tool consultar_conocimiento
```

### API de prueba
```http
GET /api/knowledge/search?q=tarifas+fibra&empresa_id=1&limit=5&threshold=0.7
Authorization: Bearer <jwt>
```

### Verificación en staging
1. Subir documentos a KB del tenant (`/api/knowledge/...`).
2. Buscar término **exacto** del documento (prueba keyword) y **sinónimo** (prueba vector).
3. Comparar resultados con `RAG_HYBRID_ENABLED=false` (solo vector) si hace falta contrastar.

### Migración Supabase
- `20260624_hybrid_kb_search.sql` — RPC keyword FTS (sin índice GIN por límite de memoria en deploy).

---

## 4. A/B testing de campañas

### Schema
| Tabla | Campos |
|-------|--------|
| `campaigns` | `ab_test_enabled`, `agent_id_b`, `ab_split_ratio` |
| `campaign_leads` | `ab_variant` |
| `encuestas` | `ab_variant` |

### Crear campaña A/B
```http
POST /api/campaigns
```
```json
{
  "name": "Test prompt voz Jun-26",
  "agent_id": 12,
  "agent_id_b": 15,
  "empresa_id": 1,
  "ab_test_enabled": true,
  "ab_split_ratio": 0.5,
  "status": "pending"
}
```

Variante **A** = `agent_id`. Variante **B** = `agent_id_b`.  
Asignación **determinista** por `(campaign_id, lead_id)` — el mismo lead siempre recibe la misma variante en reintentos.

### Métricas
```http
GET /api/campaigns/{campaign_id}/ab-stats
```

Respuesta ejemplo:
```json
{
  "campaign_id": 42,
  "ab_test_enabled": true,
  "ab_split_ratio": 0.5,
  "total_calls": 120,
  "variants": {
    "A": { "calls": 58, "completed": 31, "completion_rate": 0.5345, "avg_score": 7.2, "agent_id": 12 },
    "B": { "calls": 62, "completed": 38, "completion_rate": 0.6129, "avg_score": 8.1, "agent_id": 15 }
  }
}
```

### Motores que respetan A/B
- `campaign_orchestrator` (tipo `orchestrated` / `use_orchestrator`)
- Goteo drip (`_dispatch_single_lead_drip`)

### Verificación en staging
1. Crear dos agentes con prompts/voces distintos (IDs 12 y 15).
2. Campaña A/B con ≥20 leads de prueba.
3. Tras dispatch, comprobar distribución ~50/50:
```sql
SELECT ab_variant, COUNT(*) FROM campaign_leads
WHERE campaign_id = 42 AND ab_variant IS NOT NULL
GROUP BY ab_variant;
```
4. Confirmar `agent_id` correcto en `encuestas` por variante.

---

## Script de verificación automática

Desde la raíz del repo:

```bash
cd backend
PYTHONPATH=. .venv/bin/python scripts/verify_advanced_ai_staging.py
```

Opciones:
```bash
# Incluir pruebas contra Supabase (RPC keyword + REST)
PYTHONPATH=. .venv/bin/python scripts/verify_advanced_ai_staging.py --supabase

# Empresa de prueba para búsqueda KB
PYTHONPATH=. .venv/bin/python scripts/verify_advanced_ai_staging.py --supabase --empresa-id 1
```

El script valida:
- Variables de entorno críticas
- Lógica local (semántico Tier 0, PII, RRF, A/B)
- Tests unitarios del paquete (`pytest` subset)
- Opcional: conectividad Supabase + RPC `search_knowledge_base_keyword`

---

## Tests unitarios (CI local)

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_semantic_router_service.py \
  tests/test_pii_sanitizer.py \
  tests/test_rag_hybrid.py \
  tests/test_campaign_ab_service.py \
  -q
```

---

## Checklist pre-producción

- [ ] `GROQ_API_KEY` en worker LiveKit y backend
- [ ] `OPENAI_API_KEY` para embeddings KB
- [ ] Migraciones Supabase aplicadas (`20260623` … `20260625`)
- [ ] Llamada prueba: transferencia semántica &lt; 1 s percibida
- [ ] Transcripción en BD sin PII en claro
- [ ] `/api/knowledge/search` devuelve resultados híbridos
- [ ] Campaña A/B con stats en `/ab-stats`
- [ ] Webhooks n8n reciben `transcription` ya sanitizada (post `guardar-encuesta`)

---

## Rollback rápido

| Feature | Desactivar sin redeploy código |
|---------|-------------------------------|
| Semántico | `SEMANTIC_ROUTING_ENABLED=false` o por agente |
| PII | `PII_SANITIZATION_ENABLED=false` |
| RAG híbrido | `RAG_HYBRID_ENABLED=false` |
| A/B | `ab_test_enabled=false` en campaña |

Reiniciar contenedores `backend` y `agent` tras cambiar `.env`.

---

## Soporte / logs

| Componente | Log prefix / archivo |
|------------|---------------------|
| Semántico | `Semantic route`, `semantic-router` |
| PII | `PII sanitization regex` |
| RAG | `[knowledge]` |
| A/B | `[AB] campaña=` |

Para incidencias, adjuntar `job_id` de la sala LiveKit y `encuesta_id` de Supabase.
