# 🚀 GUÍA RÁPIDA: Desplegar en Portainer

## ⚡ Pasos Rápidos (5 minutos)

### 1️⃣ En Portainer

1. **Stacks** → **Add Stack**
2. **Name**: `ausarta-robot`
3. **Build method**: **Repository**
4. **Repository URL**: `https://github.com/inigosolana/Ausarta_Robot_Varios_AGENTES`
5. **Compose path**: `docker-compose.yml`

### 2️⃣ Variables de Entorno

Haz clic en **"Add environment variable"** y añade estas:

**⚠️ IMPORTANTE: Usa tus propias credenciales, estos son solo ejemplos**

```
# LiveKit
LIVEKIT_URL=wss://tu-proyecto.livekit.cloud
LIVEKIT_API_KEY=tu_livekit_api_key
LIVEKIT_API_SECRET=tu_livekit_api_secret
SIP_OUTBOUND_TRUNK_ID=ST_tu_trunk_id

# AI Providers
DEEPGRAM_API_KEY=tu_deepgram_api_key
CARTESIA_API_KEY=tu_cartesia_api_key
GROQ_API_KEY=tu_groq_api_key
OPENAI_API_KEY=tu_openai_api_key
GOOGLE_API_KEY=tu_google_api_key

# Supabase (Backend + Frontend)
SUPABASE_URL=https://tu-proyecto.supabase.co
SUPABASE_KEY=tu_supabase_anon_key
VITE_SUPABASE_URL=https://tu-proyecto.supabase.co
VITE_SUPABASE_ANON_KEY=tu_supabase_anon_key
```

**💡 Tips**:
- Las variables `VITE_*` se inyectan en el frontend en tiempo de build
- Si solo pones `SUPABASE_URL` y `SUPABASE_KEY`, se usarán como fallback para el frontend también
- La SUPABASE_KEY es la clave **anon** (pública), no la service_role

### 3️⃣ Deploy

**Deploy the stack** → Espera 5-10 minutos

### 4️⃣ Verificar

**Containers** → Deberías ver 2 contenedores:
- ✅ `ausarta-frontend` (puerto 80)
- ✅ `ausarta-backend` (puerto 8002 → 8001)

### 5️⃣ Acceder

🌐 **Frontend**: http://tu-servidor → Verás la pantalla de **Login**
📡 **API**: http://tu-servidor:8002/docs

### 6️⃣ Crear Primer Usuario (Superadmin)

El primer usuario se crea desde la consola de Supabase o con el script:

1. Ve a **Supabase Dashboard** → **Authentication** → **Users**
2. Haz clic en **"Add user"** → **"Create new user"**
3. Rellena email y contraseña
4. Una vez creado, ve a **Table Editor** → **user_profiles**
5. Edita el registro del usuario y cambia `role` a `superadmin`

¡Ya puedes iniciar sesión como **Superadmin** y gestionar todo!

---

## 📋 Checklist Rápido

- [ ] Portainer instalado y corriendo
- [ ] Repositorio GitHub accesible
- [ ] Variables de entorno configuradas (AI + LiveKit + Supabase)
- [ ] Stack desplegado sin errores
- [ ] 2 contenedores en estado "running"
- [ ] Frontend carga la pantalla de Login
- [ ] Backend API responde en /docs
- [ ] Primer superadmin creado

---

## 🆘 Problemas Comunes

### ❌ "Build failed"
→ Revisa logs del contenedor que falló
→ Verifica que todas las variables estén configuradas
→ Asegúrate de que las variables `VITE_SUPABASE_URL` estén en las env vars

### ❌ "Backend unhealthy"
→ Ve a Logs del backend
→ Verifica credenciales de LiveKit y Supabase

### ❌ "Frontend no carga" / Login no funciona
→ Verifica que VITE_SUPABASE_URL y VITE_SUPABASE_ANON_KEY están configuradas
→ Si las cambiaste, haz **"Pull and redeploy"** (se necesita rebuild)

### ❌ "Error de autenticación"
→ Verifica que el usuario existe en Supabase Auth
→ Verifica que `user_profiles` tiene el registro con el rol correcto

---

## 📞 URLs de Acceso

Reemplaza `tu-servidor` con tu IP o dominio:

- **Frontend**: http://tu-servidor (puerto 80)
- **API Backend**: http://tu-servidor:8002
- **API Docs**: http://tu-servidor:8002/docs
- **Portainer**: http://tu-servidor:9000

---

## 🔄 Actualizar el Stack

1. **Stacks** → **ausarta-robot**
2. **Pull and redeploy** (✅ Esto rebuildea el frontend con las variables VITE_*)
3. Espera ~5 minutos

---

## 👥 Sistema de Roles

| Rol | Permisos |
|-----|----------|
| **Superadmin** | Acceso total. Crea admins. |
| **Admin** | Acceso total. Crea y gestiona usuarios. |
| **User** | Solo ve los módulos que le habilite su admin. |

---

## 🎉 ¡Listo!

Tu plataforma está corriendo. Ahora puedes:
1. Iniciar sesión con el Superadmin
2. Ir a **Crear Agentes** → Crear tus agentes de voz
3. Ir a **Llamada Prueba** → Probar una llamada rápida
4. Ir a **Usuarios** → Crear admins y usuarios

**Documentación completa**: Ver `DOCKER_DEPLOYMENT.md`
