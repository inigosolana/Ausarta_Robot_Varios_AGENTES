# Configurar nodos Notion en n8n (5 minutos)

Los workflows ya tienen nodos **Code** que llaman a la API de Notion (upsert automático).
Solo tienes que pegar **1 token** y **5 Database IDs**.

---

## 1. Crear integración Notion

1. https://www.notion.so/my-integrations → **New integration**
2. Nombre: `Ausarta HQ Sync`
3. Copia el **Internal Integration Secret** → es tu `NOTION_TOKEN`

En cada base de datos de Notion:
- `...` → **Connections** → invita **Ausarta HQ Sync**

---

## 2. Obtener Database IDs

Abre cada tabla en Notion. La URL tiene este formato:

```
https://www.notion.so/TU_WORKSPACE/abcdef1234567890abcdef1234567890?v=...
                              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                              Este es el Database ID (32 caracteres)
```

Anota:

| Variable en n8n | Base de datos |
|-----------------|---------------|
| `PEGA_DB_CLIENTES` | Clientes (Empresas) |
| `PEGA_DB_USUARIOS` | Usuarios |
| `PEGA_DB_LLAMADAS` | Llamadas |
| `PEGA_DB_AGENTES` | Agentes |
| `PEGA_DB_INCIDENCIAS` | Incidencias |

---

## 3. Nombres de columnas en Notion (deben coincidir exactamente)

### Clientes
`ID` (Number) · `Nombre` (Title) · `Plan` (Select) · `Llamadas este mes` (Number) · `Límite` (Number) · `Agentes` (Number)

Opcional con fórmula: `% uso` · `Estado`

### Usuarios
`ID` (Text) · `Nombre` (Title) · `Email` (Email) · `Rol` (Select) · `Empresa ID` (Number) · `Activo` (Checkbox)

### Llamadas
`ID` (Number) · `Empresa ID` (Number) · `Agente` (Text) · `Duración (seg)` (Number) · `Fecha` (Date) · `Resultado` (Select) · `Minutos` (Number)

### Agentes
`ID` (Number) · `Nombre` (Title) · `Empresa ID` (Number) · `Tipo` (Select: entrante/saliente) · `Activo` (Checkbox)

### Incidencias
`Título` (Title) · `Severidad` (Select: P0/P1/P2/P3) · `Estado` (Select: Abierta/En curso/Resuelta) · `Detectado` (Date) · `Notas` (Text)

---

## 4. Pegar token e IDs en n8n

Abre cada workflow en http://79.72.57.62:5678

### Workflow `xLszAuzoH7WfZOOU` — Webhook Supabase → Notion

Edita estos 4 nodos Code (doble clic → JavaScript):

| Nodo | Sustituir |
|------|-----------|
| **Notion Clientes** | `PEGA_TU_NOTION_TOKEN` y `PEGA_DB_CLIENTES` |
| **Notion Usuarios** | `PEGA_TU_NOTION_TOKEN` y `PEGA_DB_USUARIOS` |
| **Notion Agentes** | `PEGA_TU_NOTION_TOKEN` y `PEGA_DB_AGENTES` |
| **Notion Llamadas** | `PEGA_TU_NOTION_TOKEN` y `PEGA_DB_LLAMADAS` |

### Workflow `viEZ0MYLHNbkttNL` — Sync diario Empresas

1. Nodo **GET Empresas** → header `X-N8N-Secret`: tu secret real
2. Nodo **Notion Clientes** → token + `PEGA_DB_CLIENTES`

### Workflow `gFKhoNeKH2COQwpZ` — Alerta llamadas cero

1. Nodos **GET Llamadas** y **GET Agentes** → `X-N8N-Secret`
2. Nodo **Notion Incidencia** → token + `PEGA_DB_INCIDENCIAS`

---

## 5. Activar workflows

Orden recomendado:

1. **Webhook Supabase → Notion** (activar primero — te da la URL del webhook)
2. **Sync diario Empresas**
3. **Alerta llamadas cero**

Toggle **Active** arriba a la derecha en cada workflow.

---

## 6. Probar

### Test manual del nodo Notion (sin Supabase)

En n8n, abre workflow Webhook → nodo **Notion Clientes** → **Execute step** con datos de prueba del nodo Map Empresas.

### Test end-to-end

```bash
curl -X POST http://79.72.57.62:8003/api/notion-sync/webhook/supabase \
  -H "Content-Type: application/json" \
  -H "X-Supabase-Webhook-Secret: TU_WEBHOOK_SECRET" \
  -d '{
    "table": "empresas",
    "type": "UPDATE",
    "record": {
      "id": 1,
      "nombre": "Ausarta Test",
      "plan": "basico",
      "max_llamadas_mes": 100,
      "llamadas_consumidas_mes": 42
    }
  }'
```

Revisa:
- n8n → **Executions** → debe salir verde
- Notion → Clientes → fila con ID=1

---

## Errores frecuentes

| Error | Solución |
|-------|----------|
| `Could not find database` | Database ID incorrecto o integración no invitada a esa tabla |
| `property X does not exist` | Nombre de columna en Notion no coincide (mayúsculas, tildes) |
| `is not a property that exists` | Tipo de columna incorrecto (ej. ID debe ser Number en Clientes) |
| `401 unauthorized` | Token incorrecto o revocado |
| `403` en GET empresas | `X-N8N-Secret` incorrecto en nodo HTTP |
