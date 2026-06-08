# AUSARTA HQ — Guía de conexión Notion + n8n + Supabase

## Arquitectura

```
Supabase (cambio en BD)
    → POST /api/notion-sync/webhook/supabase  (backend Ausarta)
    → n8n webhook notion-sync-supabase
    → Notion (upsert en base de datos)

n8n (schedule diario 7:00)
    → GET /api/notion-sync/empresas  (con X-N8N-Secret)
    → Notion upsert Clientes

n8n (cada hora L-V 8-20h)
    → GET /api/notion-sync/llamadas?desde=hace1hora
    → si total=0 → crear Incidencia P2 en Notion
```

---

## PASO 1 — Crear estructura en Notion (10 min)

Crea un workspace **AUSARTA HQ** con esta jerarquía:

```
🏠 AUSARTA HQ
├── 📊 Dashboard diario
├── 🗂️ PRODUCTO
│   ├── 🗺️ Roadmap
│   ├── ✅ Tareas & Sprints
│   └── 🐛 Bugs & Issues
├── 📈 NEGOCIO
│   ├── 🏢 Clientes (Empresas)
│   ├── 👥 Usuarios
│   └── 💰 MRR & Métricas
├── ⚙️ OPERACIONES
│   ├── 📞 Llamadas
│   ├── 🤖 Agentes
│   └── 🚨 Incidencias
└── 📓 DECISIONES & NOTAS
    ├── 📋 Decision Log
    └── 🔍 Análisis semanales
```

### Base de datos 1: Clientes (Empresas)

| Columna Notion | Tipo | Origen / notas |
|----------------|------|----------------|
| ID | Number | `record.id` — clave de match para upsert |
| Nombre | Title | `record.nombre` |
| Plan | Select | basico / profesional / enterprise |
| Llamadas este mes | Number | `llamadas_consumidas_mes` |
| Límite | Number | `max_llamadas_mes` |
| % uso | Formula | `prop("Llamadas este mes") / prop("Límite") * 100` |
| Agentes | Number | conteo desde sync |
| Última actualización | Date | `updated_at` |
| Estado | Formula | si % uso > 90 → Crítico, > 70 → Atención, resto → OK |

### Base de datos 2: Usuarios

| Columna | Tipo | Origen |
|---------|------|--------|
| ID | Rich text | `user_profiles.id` (UUID) |
| Nombre | Title | `full_name` |
| Email | Email | `email` |
| Rol | Select | superadmin / admin / user |
| Empresa | Relation → Clientes | por `empresa_id` |
| Activo | Checkbox | `is_active` |
| Creado | Date | `created_at` |
| Última modificación | Date | `updated_at` |

### Base de datos 3: Llamadas (solo append)

| Columna | Tipo | Origen |
|---------|------|--------|
| ID | Number | `encuestas.id` |
| Empresa | Relation → Clientes | `empresa_id` |
| Agente | Rich text | nombre del agente |
| Duración (seg) | Number | `seconds_used` |
| Fecha | Date | `fecha` |
| Resultado | Select | status / completada |
| Minutos | Number | `seconds_used / 60` |

### Base de datos 4: Agentes

| Columna | Tipo | Origen |
|---------|------|--------|
| ID | Number | `agent_config.id` |
| Nombre | Title | `name` |
| Empresa | Relation → Clientes | `empresa_id` |
| Tipo | Select | entrante / saliente |
| Activo | Checkbox | default true |
| Creado | Date | `created_at` |

### Base de datos 5: Tareas & Sprints (manual)

| Columna | Tipo | Valores |
|---------|------|---------|
| Tarea | Title | — |
| Área | Select | Producto / Bug / Operaciones / Negocio |
| Estado | Select | Por hacer / En progreso / En revisión / Hecho |
| Prioridad | Select | Crítica / Alta / Media / Baja |
| Sprint | Text | ej. Sprint 1 · Junio |
| Fecha límite | Date | — |
| Notas | Text | — |

### Base de datos 6: Incidencias

| Columna | Tipo | Valores |
|---------|------|---------|
| Título | Title | — |
| Severidad | Select | P0 / P1 / P2 / P3 |
| Estado | Select | Abierta / En curso / Resuelta |
| Empresa afectada | Relation → Clientes | opcional |
| Detectado | Date | auto |
| Resuelto | Date | — |
| Causa raíz | Text | — |
| Notas | Text | — |

### Dashboard diario — 5 linked views

1. **Incidencias abiertas** → filtro Estado = Abierta
2. **Actividad de ayer** → Llamadas, Fecha = ayer
3. **Clientes con alertas** → Clientes, % uso > 80
4. **Tareas para hoy** → Tareas, Fecha límite = hoy OR Estado = En progreso
5. **Notas rápidas** → bloque de texto libre en la página

---

## PASO 2 — Variables de entorno backend

Añade en Portainer / `.env` del backend:

```env
SUPABASE_WEBHOOK_SECRET=genera_un_secret_largo_aleatorio
NOTION_SYNC_N8N_WEBHOOK_URL=https://n8n.ausarta.net/webhook/notion-sync-supabase
N8N_PROXY_SECRET=el_mismo_que_ya_tienes
```

Redeploy del contenedor `backend`.

---

## PASO 3 — Webhooks en Supabase (5 min)

Dashboard Supabase → **Database → Webhooks** → New webhook (×4):

| Nombre | Tabla | Eventos | URL |
|--------|-------|---------|-----|
| notion-empresas | empresas | INSERT, UPDATE | `https://TU_BACKEND/api/notion-sync/webhook/supabase` |
| notion-users | user_profiles | INSERT, UPDATE, DELETE | misma URL |
| notion-agentes | agent_config | INSERT, UPDATE | misma URL |
| notion-llamadas | encuestas | INSERT | misma URL |

Header en todos:
```
X-Supabase-Webhook-Secret: <mismo valor que SUPABASE_WEBHOOK_SECRET>
```

---

## PASO 4 — Credencial Notion en n8n

1. https://www.notion.so/my-integrations → New integration → **Ausarta HQ Sync**
2. Copia el **Internal Integration Token**
3. En n8n → Credentials → Notion API → pega el token
4. En cada base de datos de Notion → `...` → Connections → invita la integración

Anota los **Database IDs** (32 chars en la URL de cada tabla):
```
NOTION_DB_CLIENTES=xxxxxxxx
NOTION_DB_USUARIOS=xxxxxxxx
NOTION_DB_LLAMADAS=xxxxxxxx
NOTION_DB_AGENTES=xxxxxxxx
NOTION_DB_INCIDENCIAS=xxxxxxxx
```

---

## PASO 5 — Workflows n8n (ya creados en tu instancia)

En tu instancia n8n (`http://79.72.57.62:5678`) ya están creados 3 workflows **inactivos**:

| Workflow | ID n8n | Qué hace |
|----------|--------|----------|
| Ausarta HQ - Webhook Supabase → Notion | `xLszAuzoH7WfZOOU` | Recibe eventos del backend y mapea por tabla |
| Ausarta HQ - Sync diario Empresas | `viEZ0MYLHNbkttNL` | 7:00 → GET empresas → upsert Notion |
| Ausarta HQ - Alerta llamadas cero | `gFKhoNeKH2COQwpZ` | Cada hora L-V 8-20h → si 0 llamadas → incidencia P2 |

### Configurar cada workflow

1. Abre el workflow en n8n
2. En nodos **HTTP Request**: cambia `TU_BACKEND_URL` por tu URL real (ej. `http://79.72.57.62:8003` o dominio público)
3. En nodos **HTTP Request**: pon tu `X-N8N-Secret` real
4. Añade nodo **Notion** después de cada Code node (o conecta el que falta):
   - Resource: Database Page
   - Operation: Create (llamadas) o Update si existe
   - Database ID: el de la tabla correspondiente
5. **Activa** el workflow (toggle arriba a la derecha)

### Webhook URL final

Tras activar el workflow webhook, la URL será:
```
https://n8n.ausarta.net/webhook/notion-sync-supabase
```
(o `http://79.72.57.62:5678/webhook/notion-sync-supabase` si no hay dominio)

---

## PASO 6 — Probar

```bash
# 1. Probar GET empresas (desde servidor o local)
curl -s -H "X-N8N-Secret: TU_SECRET" \
  https://TU_BACKEND/api/notion-sync/empresas | jq '.total'

# 2. Probar webhook (simula Supabase)
curl -s -X POST https://TU_BACKEND/api/notion-sync/webhook/supabase \
  -H "Content-Type: application/json" \
  -H "X-Supabase-Webhook-Secret: TU_WEBHOOK_SECRET" \
  -d '{"table":"empresas","type":"UPDATE","record":{"id":1,"nombre":"Test","plan":"basico","max_llamadas_mes":100,"llamadas_consumidas_mes":50}}'

# 3. Ver ejecución en n8n → Executions
# 4. Ver fila nueva/actualizada en Notion → Clientes
```

---

## Rutina diaria (5 min mañana)

1. Abre **Dashboard diario**
2. Revisa **Incidencias abiertas** (si hay → atender primero)
3. Mira **Actividad de ayer** en Llamadas
4. Comprueba **Clientes con alertas** (% uso > 80)
5. Revisa **Tareas para hoy**

Viernes (+15 min): convierte Notas rápidas en Análisis semanal.

---

## Endpoints backend disponibles

| GET | Query params | Uso |
|-----|--------------|-----|
| `/api/notion-sync/empresas` | — | Sync clientes |
| `/api/notion-sync/users` | — | Sync usuarios |
| `/api/notion-sync/agentes` | — | Sync agentes |
| `/api/notion-sync/llamadas` | `desde`, `horas`, `empresa_id`, `limit` | Llamadas + alertas |

Auth: header `X-N8N-Secret` o JWT superadmin.
