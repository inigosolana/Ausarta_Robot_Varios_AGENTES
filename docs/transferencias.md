# Transferencias de llamada: extensiones internas y números externos

**Versión:** 2.0  
**Última actualización:** 2026-06

---

## Resumen

El endpoint `POST /api/calls/transfer` (y su alias `POST /api/telephony/transfer`) acepta como destino tanto **extensiones internas** del PBX como **números de teléfono externos** (móviles, fijos, nacionales o E.164).

El backend detecta automáticamente si el destino es interno o externo y aplica lógica diferente:

| Tipo | Detección | Comportamiento |
|------|-----------|----------------|
| Extensión interna | ≤ 5 dígitos y presente en `yeastar_extensions` | Verifica estado (idle/available). Si ocupada → 409 |
| Número externo | > 5 dígitos, contiene `+`, o no está en `yeastar_extensions` | Salta check de estado. Transfiere directamente |

---

## Cómo funciona la detección interna/externa

La función `_is_internal_extension(empresa_id, target)` aplica:

1. **Heurística rápida**: si el destino tiene más de 5 dígitos puros → externo.
2. **Consulta Supabase**: busca en `yeastar_extensions` (empresa_id + extension_number).
   - Si está → interno.
   - Si la tabla tiene registros pero no encuentra el destino → externo.
3. **Fallback sin BD**: si ≤ 5 dígitos sin '+' → se trata como interno.

---

## Requisito Yeastar para números externos

Para que una transferencia a número externo funcione el Yeastar del cliente debe:

1. **Tener una ruta saliente activa** que alcance números PSTN externos.
2. **El agente/extensión de origen** debe tener permisos para usar esa ruta saliente.
3. Opcionalmente, si el plan de numeración requiere marcar un dígito de acceso a ruta (ej. "0" para marcar línea exterior), configurar `outbound_prefix`.

> **⚠️ TODO verificar con Yeastar**: Se ha confirmado que la API `call/transfer` acepta el campo `number` tanto para extensiones internas como para números externos (con el plan de marcación correcto). Sin embargo, el comportamiento exacto varía por firmware de P-Series (84.x, 86.x) y por configuración de rutas salientes. Recomendamos hacer una prueba controlada en el PBX del cliente antes de activar en producción.

---

## Configurar `outbound_prefix` por empresa

El `outbound_prefix` es el dígito (o dígitos) que se anteponen al número externo antes de enviarlo al Yeastar. Es necesario cuando el plan de numeración del cliente requiere marcar un prefijo para acceder a la ruta saliente (ej. "0" o "9").

### Método 1: En el request (por llamada)

```json
POST /api/calls/transfer
{
  "room_name": "empresa_42_encuesta_123",
  "empresa_id": 42,
  "call_id": "callid-xxx",
  "extension": "612345678",
  "outbound_prefix": "0"
}
```

El número enviado a Yeastar será `"0612345678"`.

### Método 2: Configuración persistente por empresa (recomendado)

Añadir campo `outbound_prefix` en la tabla `company_yeastar_configs`:

```sql
-- Migración
ALTER TABLE company_yeastar_configs ADD COLUMN IF NOT EXISTS outbound_prefix TEXT DEFAULT '';

-- Configurar prefijo para empresa_id=42
UPDATE company_yeastar_configs
SET outbound_prefix = '0'
WHERE empresa_id = 42;
```

El backend lo lee automáticamente para todas las transferencias externas de esa empresa sin necesidad de pasarlo en cada request.

### Sin prefijo

Si el Yeastar puede marcar números externos directamente (sin prefijo de acceso a línea):

```sql
UPDATE company_yeastar_configs SET outbound_prefix = '' WHERE empresa_id = 42;
```

---

## Formato de números externos aceptados

El backend normaliza los números eliminando caracteres no numéricos antes de enviarlos a Yeastar.

| Entrada | Normalizado |
|---------|------------|
| `+34 612-34 56 78` | `+34612345678` |
| `912 34 56 78` | `912345678` |
| `(912) 345-678` | `912345678` |

**Requisitos mínimos:**
- Al menos 6 dígitos
- Solo contener: dígitos, espacios, `+`, `-`, `(`, `)`
- El `+` solo es válido al inicio (formato E.164)

Ejemplos **inválidos** (devuelven 400):
- `123` — demasiado corto
- `abc-123` — contiene letras
- `612abc789` — letras intercaladas

---

## Sincronizar extensiones internas

Para que la detección de extensiones internas funcione correctamente, sincroniza las extensiones desde el PBX:

```bash
# Via API (requiere token admin)
curl -X POST "https://api.ausarta.com/api/empresas/42/extensions/sync" \
  -H "Authorization: Bearer $JWT"
```

Esto actualiza la tabla `yeastar_extensions` con las extensiones reales del Yeastar.

Si la tabla está vacía, el backend usa la heurística de longitud (≤ 5 dígitos = interno).

---

## Respuesta de transferencia exitosa

```json
{
  "status": "ok",
  "message": "Transferencia iniciada en la centralita",
  "empresa_id": 42,
  "room_name": "empresa_42_encuesta_123",
  "call_id": "callid-xxx",
  "target_extension": "612345678",
  "transfer_type": "external",
  "extension_status": "skipped_external"
}
```

- `transfer_type`: `"internal"` o `"external"`
- `extension_status`: estado de la extensión si es interna, `"skipped_external"` si es externa

---

## Códigos de error

| Código | Causa |
|--------|-------|
| 400 | Número externo inválido (formato incorrecto o demasiado corto) |
| 400 | Destino de transferencia no configurado |
| 409 | Extensión interna ocupada (status ≠ idle/available) |
| 409 | Llamada sin channel_id de Yeastar (webhook 30011 no recibido) |
| 502 | Error en la API de Yeastar al ejecutar la transferencia |

---

## Logging

Cada transferencia emite dos líneas de log en JSON (cuando `LOG_FORMAT=json`):

```json
{"level": "INFO", "msg": "[transfer] empresa=42 room=... destino='612345678' tipo=external"}
{"level": "INFO", "msg": "✅ [transfer] empresa=42 call_id=... → 612345678 (external) room=..."}
```

También se guarda en `encuestas.datos_extra`:

```json
{
  "transfer_extension": "612345678",
  "transfer_type": "external",
  "transfer_room": "empresa_42_encuesta_123"
}
```

---

## Configuración del agente LiveKit

En `backend/agents/agent_tools.py`, la función `transferir_a_agente_humano` puede recibir un número externo si el LLM lo extrae de la conversación:

```python
@function_tool
async def transferir_a_agente_humano(context: RunContext, destino: str = "1000") -> str:
    """
    Transfiere la llamada a una extensión interna o número de teléfono externo.
    destino: extensión interna (ej. '1001') o número externo (ej. '612345678').
    """
```

El agente puede decidir transferir a un número externo si el cliente lo pide o si las instrucciones del agente así lo indican.
