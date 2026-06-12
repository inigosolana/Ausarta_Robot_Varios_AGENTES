# Health-check Yeastar por empresa

**Versión:** 1.0  
**Última actualización:** 2026-06

---

## Qué hace

El worker ARQ ejecuta periódicamente `check_yeastar_health_task`, que:

1. Recorre todas las empresas con `company_yeastar_configs.is_active = true`.
2. Comprueba conectividad contra el PBX Yeastar (timeout 5 s, petición ligera de autenticación).
3. Actualiza `health_status`, `consecutive_failures` y `last_health_check_at` en BD.
4. Si hay **3 fallos consecutivos** (~3 ciclos del cron):
   - Marca el PBX como `down`.
   - Pausa automáticamente las campañas `active` / `running` de esa empresa.
   - Envía alerta Telegram.
5. Cuando el PBX vuelve a responder tras estar `down`:
   - Marca `health_status = ok`.
   - Reanuda campañas que fueron pausadas por el health-check (si no las tocó un operador).
   - Envía alerta Telegram de recuperación.

Un fallo al comprobar la empresa A **nunca bloquea** la comprobación de la empresa B.

---

## Configuración

### Intervalo del cron

Variable de entorno en el servicio **ARQ worker** (no en la API):

```bash
YEASTAR_HEALTH_CHECK_INTERVAL_SECONDS=120   # default: 120 segundos (cada 2 minutos)
```

El worker traduce el intervalo a minutos en el cron de ARQ (`minute={0, 2, 4, ...}` para 120 s).

### Umbral de fallos

Constante en código (`services/yeastar_health_service.py`):

```python
FAILURE_THRESHOLD = 3  # 3 fallos consecutivos antes de marcar down
```

---

## Estados `health_status`

| Valor | Significado |
|-------|-------------|
| `unknown` | Aún no se ha ejecutado ningún check (o recién configurado) |
| `ok` | Último check exitoso |
| `down` | 3+ fallos consecutivos; campañas pueden estar pausadas automáticamente |

---

## Campos en campañas (pausa automática)

| Campo | Descripción |
|-------|-------------|
| `paused_by_health_check` | `true` si la pausa la hizo el health-check |
| `paused_reason` | `"Yeastar sin respuesta"` |
| `status_before_health_pause` | Estado previo (`active` / `running`) para reanudar |
| `health_paused_at` | Timestamp de la pausa automática |

### Respeto a pausas manuales

- Si el operador pausa una campaña manualmente (`POST /campaigns/{id}/stop`), se limpian los flags de health-check → **no se reanudará sola**.
- Si el operador modifica una campaña después de la pausa automática (`updated_at > health_paused_at`), el health-check **no la reanuda** al recuperarse el PBX.

---

## API para el frontend

### Consultar estado

```http
GET /api/empresas/{empresa_id}/yeastar/health
Authorization: Bearer <JWT>
```

Respuesta ejemplo:

```json
{
  "empresa_id": 42,
  "configured": true,
  "health_status": "down",
  "last_health_check_at": "2026-06-13T10:00:00+00:00",
  "consecutive_failures": 3,
  "failure_threshold": 3,
  "campaigns_paused_count": 2,
  "campaigns_paused_by_health": [
    {"id": 10, "name": "Outbound Q2", "status": "paused", "paused_reason": "Yeastar sin respuesta"}
  ]
}
```

### Forzar re-check (admin)

```http
POST /api/empresas/{empresa_id}/yeastar/health/check
Authorization: Bearer <JWT>
```

Ejecuta el mismo flujo que el cron para una sola empresa (útil si algo quedó atascado).

---

## Qué hacer si algo queda atascado

1. **Verificar el PBX** del cliente (URL, credenciales, firewall).
2. **Forzar re-check** desde Telefonía (botón corazón) o `POST .../yeastar/health/check`.
3. Si el PBX está bien pero `health_status` sigue en `down`:
   ```sql
   UPDATE company_yeastar_configs
   SET health_status = 'ok', consecutive_failures = 0
   WHERE empresa_id = 42;
   ```
4. **Reanudar campañas manualmente** desde la UI de campañas (`POST /campaigns/{id}/start`).
5. Revisar logs del worker: `[yeastar_health]`.

---

## Migración SQL

Aplicar `backend/supabase/migrations/20260613_yeastar_health.sql`:

- `company_yeastar_configs`: `health_status`, `last_health_check_at`, `consecutive_failures`
- `campaigns`: `paused_reason`, `paused_by_health_check`, `status_before_health_pause`, `health_paused_at`

---

## Telegram (opcional)

Si `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` están configurados, se envían alertas:

- Caída: `🔴 Yeastar de {empresa} no responde (N fallos) — X campaña(s) pausada(s)`
- Recuperación: `✅ Yeastar de {empresa} recuperado, X campaña(s) reanudada(s)`

**Sin Telegram configurado el health-check funciona igual** (pausa/reanuda campañas); solo se omiten las notificaciones.

---

## Referencias

- `backend/tasks/yeastar_health.py` — tarea ARQ
- `backend/services/yeastar_health_service.py` — lógica de negocio
- `backend/services/yeastar_service.py` — `YeastarClient.health_check()`
- `src/views/TelephonyView.tsx` — indicador verde/rojo/gris en UI
