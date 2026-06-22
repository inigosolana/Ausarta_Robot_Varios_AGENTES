# n8n — Ausarta Robot

Instancia activa: **https://n8n.ausarta.net**

## Webhooks usados por el backend

| Workflow | Path | Uso |
|---|---|---|
| `Recuperar_Password_Ausarta_v1` | `fbdb6333-c473-493a-a1da-6c1756d5ae04` | `POST /api/auth/password-reset` |
| `Invitacion_Usuarios_Ausarta_Robot_v3` | `d0952789-a4a1-4eae-b0db-494356a9e3fa` | Crear usuario (admin) |
| `Orquestador de Campañas de Goteo` | `campana-goteo-v1` | Llamadas salientes drip |
| `Procesamiento de Transcripciones` | `transcripciones-voice-ai` | Post-llamada + LLM |
| `Sincronización CRM` | `crm-sync` | Integración CRM (UI) |

Todas las llamadas backend → n8n deben incluir `X-N8N-Secret` (`N8N_PROXY_SECRET` en Portainer).

## URLs del backend (dominio nuevo)

Los nodos HTTP Request apuntan a **`FRONTEND_URL`** (producción: `${FRONTEND_URL}`, mismo origen que nginx `/api/`).

## Migración de dominio

```bash
N8N_API_KEY=<tu_api_key> python3 n8n/scripts/migrate_workflows_ausarta_net.py
```

Variables opcionales: `N8N_API_URL`, `AUSARTA_BACKEND_URL`, `FRONTEND_URL`.
