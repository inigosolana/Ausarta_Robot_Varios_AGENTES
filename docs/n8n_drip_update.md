# Actualización del Orquestador de Campañas n8n

Para implementar el sistema de **Campaña por Goteo (Drip Campaign)**, debes modificar tu flujo actual de n8n para que procese un lead a la vez y notifique al backend al finalizar.

## 1. Nodo de Entrada: Webhook
Configura el nodo Webhook de entrada para que reciba los datos de un solo lead:
- **HTTP Method**: POST
- **Path**: `classify-agent`
- **Response Mode**: `onReceived` (responde rápido al backend para que este pueda gestionar el tiempo de espera).

**Cuerpo esperado (JSON):**
```json
{
  "phoneNumber": "+34600000000",
  "leadId": 123,
  "agentId": 1,
  "campaignId": 10,
  "customerName": "Nombre Cliente"
}
```

## 2. Lanzar Llamada LiveKit
Utiliza el nodo de LiveKit (o la lógica que ya tengas) para iniciar la llamada. Asegúrate de pasar el `leadId` y el `phoneNumber`.

## 3. Esperar y Capturar Resultado
Después de que la llamada termine, recupera los datos de la transcripción y el estado final (`completed`, `failed`).

## 4. Nodo Final: HTTP Request (Notificar al Backend)
Este es el paso crucial para cerrar el ciclo y que el backend sepa que la llamada ha terminado (y que el frontend se actualice).

- **Method**: POST
- **URL**: `http://localhost:8003/api/campaigns/webhook/call-result` 
  *(Nota: Si n8n corre en Docker y el backend también, usa el nombre del contenedor o la IP de la red interna, ej: `http://api-backend:8003/...`)*
- **Body Parameters (JSON)**:
  - `lead_id`: `{{ $json.leadId }}` (el recibido en el paso 1)
  - `status`: `{{ $json.status }}` (ej: "completed", "failed", "voicemail")
  - `duration`: `{{ $json.duration }}`
  - `transcription`: `{{ $json.transcription }}`

## Beneficios del nuevo flujo:
1. **Estabilidad**: Ya no se lanzan 20 llamadas a la vez, evitando ser bloqueados por el proveedor SIP o saturar la CPU.
2. **Control**: Si pausas la campaña en el Dashboard, el backend dejará de enviar el siguiente lead en la próxima iteración.
3. **Persistencia**: Los resultados se guardan inmediatamente al terminar la llamada a través del nuevo Webhook.
