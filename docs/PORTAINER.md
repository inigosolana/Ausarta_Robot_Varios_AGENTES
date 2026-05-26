# Despliegue en Portainer

## Error: `env file /data/compose/XX/.env not found`

Portainer despliega el stack en `/data/compose/<id>/` y **no crea** un archivo `.env` automáticamente. Ese archivo no va en Git (contiene secretos).

### Solución (recomendada)

1. En Portainer: **Stacks** → tu stack → **Editor** (o **Update the stack**).
2. Baja hasta **Environment variables** (o **Env**).
3. Pega las variables desde `.env.example` del repo (valores reales, no los placeholders).
4. Variables **obligatorias** mínimas:

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
