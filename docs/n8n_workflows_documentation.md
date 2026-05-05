# Documentación de Workflows n8n - Ausarta Voice AI

Este documento detalla el propósito y funcionamiento de los flujos de trabajo (workflows) configurados en n8n para la plataforma Ausarta Voice AI.

## 🚀 Workflows Críticos del Sistema

### 1. Orquestador de Campañas - Ausarta Voice AI
- **Frecuencia**: Cada 1 minuto.
- **Propósito**: Es el motor principal de llamadas. Escanea la base de datos en busca de campañas en estado `running`. Para cada campaña activa, extrae el siguiente número de teléfono (lead) pendiente y realiza una petición HTTP al servidor de voz para iniciar la llamada.
- **Funcionamiento**: Implementa un bucle (Split in Batches) para procesar múltiples campañas y leads de forma secuencial, evitando la saturación del sistema.

### 2. Universal API Monitor - Ausarta Voice AI
- **Frecuencia**: Cada 1 hora.
- **Propósito**: Supervisa la salud y el consumo de todas las APIs externas (OpenAI, Groq, Deepgram, ElevenLabs, Cartesia, Google AI).
- **Funcionamiento**: Consulta los endpoints de cuota de cada proveedor, agrega los resultados y guarda una copia en la tabla `api_usage_cache`. Esto permite que el Dashboard de la web muestre el estado de los servicios al instante sin esperar a las APIs externas.

### 3. Sistema de Alertas - Ausarta Voice AI
- **Propósito**: Notificar incidencias críticas.
- **Funcionamiento**: Escucha eventos del sistema (como fallos repetitivos en una campaña o falta de saldo en una API) y centraliza las alertas para enviarlas a los desarrolladores o administradores mediante webhooks de Slack/Discord o notificaciones internas.

---

### 4. Sincronización CRM - Ausarta Voice AI
- **Propósito**: Automatizar la exportación de resultados.
- **Funcionamiento**: Una vez que una llamada termina y se ha generado la transcripción y las puntuaciones, este workflow empuja esos datos hacia el CRM externo o sistema de tickets (como GLPI), asegurando que la información comercial esté siempre al día.

---

## 🛠️ Workflows de Gestión de Usuarios

### 5. Invitación_Usuarios_Ausarta_Robot_v3
- **Propósito**: Onboarding de nuevos miembros.
- **Funcionamiento**: Se activa cuando un administrador crea un nuevo usuario. Genera un email de bienvenida con las instrucciones de acceso para asegurar una transición fluida a la plataforma.

### 6. Recuperar_Password_Ausarta_v1
- **Propósito**: Seguridad y autoservicio.
- **Funcionamiento**: Maneja las solicitudes de "olvidé mi contraseña", generando tokens seguros y enviando los enlaces de recuperación correspondientes.

---

## 📈 Workflows Auxiliares y de Mantenimiento

### 7. Cache System Refresher - Ausarta UI
- **Propósito**: Optimizar la experiencia de usuario.
- **Funcionamiento**: Realiza limpiezas periódicas de la base de datos y refresca vistas materializadas o tablas de estadísticas para que las gráficas del Dashboard carguen rápidamente para todos los clientes.

### 8. Auditoría de Costos de API
- **Propósito**: Control financiero.
- **Funcionamiento**: Realiza un desglose detallado del gasto real por campaña, permitiendo a Ausarta saber exactamente cuánto ha costado cada interacción en términos de tokens y minutos de procesamiento.

---

## 🔍 Notas de Mantenimiento
- Todos los archivos JSON de estos workflows se encuentran en el repositorio en la carpeta `/n8n/workflows/`.
- Tras cualquier cambio en las variables de entorno (`.env`), el workflow **Universal API Monitor** debe ser revisado para asegurar que las nuevas claves tienen permisos de consulta de cuota.
