# 🐳 Despliegue en Docker con Portainer

Guía completa para desplegar Ausarta Robot v2.0 en Docker usando Portainer.

## 📦 Estructura Docker

```
ausarta-robot/
├── docker-compose.yml          # Orquestación de servicios
├── .env                        # Variables de entorno
├── Dockerfile                  # Frontend (React + Nginx)
├── nginx.conf                  # Configuración Nginx
├── backend/
│   ├── Dockerfile              # Backend (API + Agent)
│   └── start.sh                # Script de inicio
└── PORTAINER_QUICKSTART.md     # Guía rápida
```

## 🏗️ Arquitectura

```
┌────────────────────────────────────────────┐
│                Docker Host                  │
│                                             │
│  ┌─────────────┐      ┌──────────────┐     │
│  │  Frontend    │      │   Backend    │     │
│  │  (Nginx)     │─────▶│  (FastAPI)   │     │
│  │  :80         │ /api │  :8001       │     │
│  └─────────────┘      └──────┬───────┘     │
│                               │              │
│                    ┌──────────▼───────┐      │
│                    │    Supabase      │      │
│                    │  (Cloud DB)      │      │
│                    │  + Auth + RLS    │      │
│                    └──────────────────┘      │
└────────────────────────────────────────────┘
```

## 🚀 Opción 1: Despliegue en Portainer (Recomendado)

### Paso 1: En Portainer

1. **Accede a Portainer** (ej: http://tu-servidor:9000)
2. **Navega a Stacks** en el menú lateral
3. **Haz clic en "Add Stack"**
4. **Configura el Stack:**
   - **Name**: `ausarta-robot`
   - **Build method**: Selecciona **"Repository"**

5. **Configuración del Repositorio:**
   - **Repository URL**: `https://github.com/inigosolana/Ausarta_Robot_Varios_AGENTES`
   - **Repository reference**: `refs/heads/main`
   - **Compose path**: `docker-compose.yml`

### Paso 2: Variables de Entorno

Haz clic en "Add environment variable" y añade cada una:

| Variable | Descripción | Ejemplo |
|----------|-------------|---------|
| `LIVEKIT_URL` | URL de LiveKit Server | `wss://tu-proyecto.livekit.cloud` |
| `LIVEKIT_API_KEY` | API Key LiveKit | `APIxxxxxxxx` |
| `LIVEKIT_API_SECRET` | API Secret LiveKit | `xxxxxxxxxxxxx` |
| `SIP_OUTBOUND_TRUNK_ID` | ID del trunk SIP | `ST_xxxxxxxx` |
| `DEEPGRAM_API_KEY` | API Key Deepgram (STT) | `xxxxxxxxxxxxx` |
| `CARTESIA_API_KEY` | API Key Cartesia (TTS) | `xxxxxxxxxxxxx` |
| `GROQ_API_KEY` | API Key Groq (LLM) | `gsk_xxxxxxxx` |
| `OPENAI_API_KEY` | API Key OpenAI | `sk-xxxxxxxx` |
| `GOOGLE_API_KEY` | API Key Google (Gemini) | `AIzaxxxxxxxx` |
| **`SUPABASE_URL`** | URL de Supabase (backend) | `https://xxx.supabase.co` |
| **`SUPABASE_KEY`** | Anon Key de Supabase | `eyJhbGci...` |
| **`VITE_SUPABASE_URL`** | URL de Supabase (frontend) | `https://xxx.supabase.co` |
| **`VITE_SUPABASE_ANON_KEY`** | Anon Key de Supabase (frontend) | `eyJhbGci...` |

> ⚠️ **IMPORTANTE**: Las variables `VITE_*` se inyectan en el frontend **en tiempo de build**. Si las cambias, necesitas hacer "Pull and redeploy" para que surtan efecto.

> 💡 **Fallback**: Si solo configuras `SUPABASE_URL` y `SUPABASE_KEY`, el docker-compose las usará como fallback para las variables `VITE_*`.

### Paso 3: Deploy

1. **Haz clic en "Deploy the stack"**
2. **Espera 5-10 minutos** la primera vez (build de Node.js + Python)

### Paso 4: Verificar

En Portainer → Containers, deberías ver:

| Contenedor | Puerto | Estado |
|------------|--------|--------|
| ✅ `ausarta-frontend` | 80 | Running |
| ✅ `ausarta-backend` | 8002 → 8001 | Running |

### Paso 5: Crear Primer Superadmin

1. Ve a **Supabase Dashboard** → **Authentication** → **Users**
2. **"Add user"** → **"Create new user"**
3. Introduce email y contraseña
4. Ve a **Table Editor** → **user_profiles**
5. Busca el registro recién creado
6. Cambia el campo `role` de `user` a **`superadmin`**
7. ¡Listo! Ya puedes iniciar sesión

---

## 🐳 Opción 2: Despliegue Local con Docker Compose

### Requisitos previos:
- Docker instalado
- Docker Compose instalado

### Pasos:

1. **Clonar el repositorio:**
```bash
git clone https://github.com/inigosolana/Ausarta_Robot_Varios_AGENTES.git
cd Ausarta_Robot_Varios_AGENTES
```

2. **Crear archivo .env:**
```bash
cp .env.example .env
# Edita .env con tus credenciales
nano .env
```

3. **Construir y ejecutar:**
```bash
docker-compose up -d --build
```

4. **Ver logs:**
```bash
# Todos los servicios
docker-compose logs -f

# Solo backend
docker-compose logs -f backend

# Solo frontend
docker-compose logs -f frontend
```

5. **Detener servicios:**
```bash
docker-compose down
```

---

## 📊 Servicios y Puertos

| Servicio | Puerto | Descripción |
|----------|--------|-------------|
| **Frontend** | 80 | Interfaz web React + Login |
| **Backend** | 8002 → 8001 | API FastAPI + LiveKit Agent |
| **Supabase** | Cloud | Base de datos + Auth + RLS |

---

## 👥 Sistema de Roles (RBAC)

### Jerarquía

```
Superadmin ─── puede crear ──▶ Admins
    │                            │
    │                            ├── puede crear ──▶ Users
    │                            └── puede gestionar permisos de Users
    │
    └── acceso total a todo
```

### Permisos por Módulo

Los admins pueden habilitar/deshabilitar módulos individualmente para cada usuario:

| Módulo | Descripción |
|--------|-------------|
| `overview` | Dashboard general |
| `create-agents` | Crear y editar agentes |
| `test-call` | Llamadas de prueba |
| `campaigns` | Gestión de campañas |
| `models` | Configuración de modelos AI |
| `telephony` | Configuración de telefonía |
| `results` | Resultados de llamadas |
| `usage` | Uso y estadísticas |

---

## 🔄 Actualizar el Stack

### Método 1: Desde Portainer
1. Ve a "Stacks" → "ausarta-robot"
2. Haz clic en "Pull and redeploy"
3. Espera ~5 minutos

### Método 2: Desde línea de comandos
```bash
cd Ausarta_Robot_Varios_AGENTES
git pull origin main
docker-compose down
docker-compose up -d --build
```

---

## 🛠️ Troubleshooting

### Backend no inicia
```bash
docker logs ausarta-backend -f
docker exec ausarta-backend env | grep SUPABASE
docker restart ausarta-backend
```

### Frontend no carga / Login falla
```bash
docker logs ausarta-frontend -f
# Si cambiaste variables VITE_*, rebuild:
docker-compose up -d --build frontend
```

### Error de autenticación
- Verifica que el usuario existe en **Supabase Auth**
- Verifica que `user_profiles` tiene el registro
- Verifica que el `role` está correctamente asignado

---

## 🔍 Health Checks

```bash
docker ps
docker inspect ausarta-backend --format='{{json .State.Health}}' | jq
docker inspect ausarta-frontend --format='{{json .State.Health}}' | jq
```

---

## 🔒 Seguridad

- **RLS habilitado** en todas las tablas de Supabase
- **Autenticación** obligatoria para acceder al frontend
- **Permisos por módulo** para usuarios regulares
- La `SUPABASE_KEY` es la clave **anon** (segura para el frontend)
- Las credenciales sensibles (service_role) NO se exponen al frontend

---

## ✅ Checklist de Despliegue

- [ ] Archivo `.env` configurado con todas las credenciales
- [ ] Puertos 80 y 8002 disponibles
- [ ] Docker y Docker Compose instalados
- [ ] Variables de entorno añadidas en Portainer (incluyendo `VITE_*`)
- [ ] Stack desplegado correctamente
- [ ] 2 contenedores corriendo (frontend, backend)
- [ ] Health checks en estado "healthy"
- [ ] Frontend carga pantalla de Login
- [ ] Primer Superadmin creado y puede iniciar sesión
- [ ] Backend API accesible en http://tu-servidor:8002/docs

---

## 🎉 ¡Listo!

Tu aplicación Ausarta Robot v2.0 está corriendo con:
- 🔐 **Login y RBAC** (Superadmin → Admin → User)
- 🤖 **Multi-agente** (crea múltiples agentes de voz)
- 📞 **Llamadas de prueba** rápidas
- 📊 **Campañas** masivas

**URLs de acceso:**
- 🌐 Frontend: http://tu-servidor
- 🔧 Backend API: http://tu-servidor:8002
- 📚 API Docs: http://tu-servidor:8002/docs
