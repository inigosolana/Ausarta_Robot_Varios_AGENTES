# Runbook: Alta de empresa nueva en Ausarta Robot

**Versión:** 2.0  
**Última actualización:** 2026-06  
**Audiencia:** SysAdmins / Platform Owners

---

## Resumen

Este runbook cubre los pasos completos para dar de alta una nueva empresa (tenant) en la plataforma Ausarta Robot. Sigue el orden exacto — algunos pasos tienen dependencias.

El script `scripts/onboard_empresa.py` automatiza los pasos marcados con 🤖.

---

## Prerrequisitos

- [ ] Acceso a Supabase (URL + service key) del proyecto
- [ ] Acceso al panel de Portainer o servidor donde corre el backend
- [ ] Credenciales del PBX Yeastar (si la empresa usa telefonía)
- [ ] Nombre comercial, email de administrador y plan elegido

---

## Paso 1 — Crear la empresa en Supabase 🤖

### Manual (SQL / Supabase Dashboard)

```sql
INSERT INTO empresas (nombre, plan, activo, datos_extra)
VALUES (
    'Nombre Empresa S.L.',
    'standard',          -- 'standard' | 'pro' | 'enterprise'
    true,
    '{"sector": "telecomunicaciones", "contacto": "admin@empresa.com"}'
)
RETURNING id;
```

Guardar el `id` resultante — se usa en todos los pasos siguientes como `{EMPRESA_ID}`.

### Automático

```bash
python scripts/onboard_empresa.py --nombre "Nombre Empresa S.L." --email admin@empresa.com
```

---

## Paso 2 — Crear usuario administrador 🤖

En el panel de Supabase → **Authentication** → **Users** → **Invite user**.

O via API:

```bash
# Con la service key de Supabase
curl -X POST "$SUPABASE_URL/auth/v1/admin/users" \
  -H "Authorization: Bearer $SUPABASE_SERVICE_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "admin@empresa.com",
    "password": "TempPass123!",
    "email_confirm": true,
    "user_metadata": {"empresa_id": {EMPRESA_ID}, "role": "admin"}
  }'
```

> **⚠️ Seguridad**: pedir al usuario que cambie la contraseña en el primer login.

---

## Paso 3 — Configurar límites de rate limiting

Si la empresa tiene un plan diferente al estándar (120 req/min):

```sql
INSERT INTO empresa_limits (empresa_id, rpm, notas)
VALUES ({EMPRESA_ID}, 120, 'Plan standard — ajustar si contrata Pro');
```

Para plan Pro (300 req/min):

```sql
INSERT INTO empresa_limits (empresa_id, rpm, notas)
VALUES ({EMPRESA_ID}, 300, 'Plan Pro');
```

Referencia: `backend/services/rate_limiter.py` — `_DEFAULT_RPM`.

---

## Paso 4 — Crear agente por defecto 🤖

El script `onboard_empresa.py` crea un agente inicial. Manualmente en la tabla `agentes`:

```sql
INSERT INTO agentes (
    empresa_id, nombre, tipo, activo,
    instrucciones, voz_id, llm_model,
    personalidad, idioma
)
VALUES (
    {EMPRESA_ID},
    'Asistente Virtual',
    'ASISTENTE_GENERAL',
    true,
    'Eres un asistente virtual amable de {Nombre Empresa}. Responde de forma concisa y profesional.',
    'es-ES-ElviraNeural',  -- voz por defecto (Cartesia o Azure)
    'llama-3.3-70b-versatile',
    '{"entusiasmo": 0.6, "velocidad": 1.0}',
    'es'
)
RETURNING id;
```

Guardar el `agent_id` resultante.

---

## Paso 5 — Configurar telefonía Yeastar (opcional)

Solo si la empresa usa llamadas entrantes/salientes a través del PBX.

```sql
INSERT INTO yeastar_config (
    empresa_id, api_url, username_enc, password_enc,
    pbx_server_ip, activo
)
VALUES (
    {EMPRESA_ID},
    'https://pbx.empresa.com:8088',
    '{username_cifrado}',   -- usar crypto_service.encrypt_data()
    '{password_cifrado}',
    '192.168.1.100',
    true
);
```

Para cifrar las credenciales:

```python
from backend.services.crypto_service import encrypt_data
print(encrypt_data("mi_password_real"))
```

### DDIs / Extensiones

```sql
-- Asignar número entrante al agente
UPDATE yeastar_config
SET ddi_inbound = '34912345678', extension_inbound = '1001'
WHERE empresa_id = {EMPRESA_ID};
```

---

## Paso 6 — Configurar BD externa del cliente (opcional)

Solo si el agente necesita consultar el CRM/ERP del cliente via `consultar_cliente`:

```sql
INSERT INTO empresa_external_db (
    empresa_id, db_type, api_url, api_key_enc, api_key_header,
    queries, activo
)
VALUES (
    {EMPRESA_ID},
    'rest',
    'https://crm.empresa.com/api',
    '{api_key_cifrada}',
    'X-Api-Key',
    '{
        "cliente_por_telefono": "clientes/buscar",
        "pedidos_cliente": "pedidos/cliente"
    }',
    true
);
```

> **⚠️ Seguridad**: el campo `queries` es la lista blanca. Solo los nombres en este JSON pueden ejecutarse. Nunca añadir SQL libre.

---

## Paso 7 — Ingestar Knowledge Base (opcional)

Si la empresa tiene documentación de productos/servicios:

```bash
# Convertir Excel a JSONL semántico
python scripts/excel_to_kb_chunks.py \
    --file docs/empresa_servicios.xlsx \
    --empresa-id {EMPRESA_ID} \
    --agent-id {AGENT_ID} \
    --output data/empresa_{EMPRESA_ID}_kb.jsonl

# Ingestar en Supabase (pgvector)
python scripts/ingest_kb_chunks.py \
    --file data/empresa_{EMPRESA_ID}_kb.jsonl \
    --empresa-id {EMPRESA_ID}
```

O subir directamente desde el panel: **Knowledge Base** → **Subir documento**.

---

## Paso 8 — Configurar personalidad del agente

En la interfaz: **Agentes** → seleccionar el agente → **Editar** → sección Personalidad.

Parámetros configurables:

| Campo | Descripción | Rango |
|-------|-------------|-------|
| `entusiasmo` | Tono emocional de la voz | 0.0–1.0 |
| `velocidad` | Velocidad de habla TTS | 0.8–1.3 |
| `critical_rules` | Instrucciones absolutas (no negociables) | texto libre |
| `idioma` | Idioma principal | `es`, `en`, `fr`, ... |

---

## Paso 9 — Verificar el onboarding

```bash
# 1. Health check del backend
curl https://api.ausarta.com/health | jq .

# 2. Verificar que el agente existe
curl -H "Authorization: Bearer $JWT" \
     "https://api.ausarta.com/api/agents?empresa_id={EMPRESA_ID}" | jq '.[].nombre'

# 3. Test de llamada de prueba (si hay telefonía)
#    Llamar al DDI configurado en Paso 5
```

---

## Paso 10 — Comunicar credenciales al cliente

Enviar por canal seguro (no email plano):

- URL del panel: `https://app.ausarta.com`
- Email de acceso: el configurado en Paso 2
- Contraseña temporal: pedir cambio en primer login
- Número DDI (si aplica)

---

## Checklist resumen

```
[ ] 1. Empresa creada en tabla empresas (obtener empresa_id)
[ ] 2. Usuario administrador creado en Supabase Auth
[ ] 3. Límite de rate limiting configurado en empresa_limits
[ ] 4. Agente por defecto creado y configurado
[ ] 5. Telefonía Yeastar configurada (si aplica)
[ ] 6. BD externa configurada con whitelist de queries (si aplica)
[ ] 7. Knowledge Base ingresada (si aplica)
[ ] 8. Personalidad del agente ajustada
[ ] 9. Health check y test de llamada realizados
[10. Credenciales comunicadas al cliente por canal seguro
```

---

## Troubleshooting

### El agente no contesta llamadas entrantes

1. Verificar `yeastar_config.activo = true`
2. Verificar que `BRIDGE_SERVER_URL_INTERNAL` apunta al contenedor correcto
3. Consultar logs: `docker logs ausarta-livekit-agent --tail 100`

### `consultar_cliente` devuelve vacío

1. Verificar `empresa_external_db.activo = true`
2. Verificar que el `query_name` usado está en el JSON `queries`
3. Verificar que la API externa responde (timeout 8s)

### Rate limiting demasiado estricto

Actualizar en Supabase (efectivo en ~60s):

```sql
UPDATE empresa_limits SET rpm = 300 WHERE empresa_id = {EMPRESA_ID};
```

---

## Referencias

- [Rate limiting](../backend/services/rate_limiter.py)
- [Seguridad multi-tenant](../backend/middleware/tenant_context.py)
- [Whitelist external DB](../backend/services/external_db_service.py)
- [AGENTS.md](../AGENTS.md)
