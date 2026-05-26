# Despliegue en Portainer

## Error: `env file /data/compose/XX/.env not found`

**Importante:** la tabla **Environment variables** de Portainer **no es** un archivo `.env` en disco. Son variables en memoria que Compose usa para sustituir `${NOMBRE}` en el `docker-compose.yml`.

El compose **ya no usa** `env_file: .env`. Las variables del panel se pasan a los contenedores con bloques `environment: ${VAR}`.

### Qué hacer

1. **Stacks** → tu stack → **Pull and redeploy** (último `main` de GitHub).
2. Deja tus variables en **Environment variables** (como en tu captura: `REDIS_PASSWORD`, `SUPABASE_URL`, etc.).
3. Comprueba que existan al menos:

```env
REDIS_PASSWORD=una_clave_segura_larga
SUPABASE_URL=https://tu-proyecto.supabase.co
SUPABASE_KEY=tu_service_role_key
SUPABASE_SERVICE_ROLE_KEY=tu_service_role_key
SUPABASE_JWT_SECRET=tu_jwt_secret
LIVEKIT_URL=wss://...
LIVEKIT_API_KEY=...
LIVEKIT_API_SECRET=...
SIP_OUTBOUND_TRUNK_ID=ST_...
DEEPGRAM_API_KEY=...
CARTESIA_API_KEY=...
GROQ_API_KEY=...
VITE_SUPABASE_URL=https://tu-proyecto.supabase.co
VITE_SUPABASE_ANON_KEY=tu_anon_key
VITE_API_URL=https://tu-dominio-api
```

5. **Pull and redeploy** el stack.

El `docker-compose.yml` usa `env_file` con `required: false`, así que **no hace falta** subir un `.env` al servidor si defines todo en el panel de Portainer.

### Alternativa: archivo `.env` en el servidor

Si prefieres un fichero:

```bash
cd /data/compose/67   # sustituye 67 por el ID de tu stack
cp .env.example .env    # o créalo a mano
nano .env               # rellena valores
```

Luego redeploy desde Portainer.

### Build del frontend

`VITE_*` se inyectan en **build time**. Si cambias `VITE_API_URL` o Supabase, haz **Rebuild** del servicio `frontend`, no solo restart.
