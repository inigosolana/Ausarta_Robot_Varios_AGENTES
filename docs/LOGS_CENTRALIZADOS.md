# Logs centralizados con Dozzle

Este proyecto incluye un servicio `dozzle` en `docker-compose.yml` para ver los logs de todos los contenedores desde una sola pantalla.

## Que hace

Dozzle lee el socket Docker del servidor y muestra en una web los logs de:

- `ausarta-v2-backend`
- `ausarta-livekit-agent`
- `ausarta-arq-worker`
- `ausarta-v2-frontend`
- `ausarta-redis`
- cualquier otro contenedor del host Docker

## Configuracion incluida

El servicio queda publicado solo en `127.0.0.1:9999` dentro del servidor:

```yaml
dozzle:
  image: amir20/dozzle:latest
  container_name: ausarta-dozzle
  restart: unless-stopped
  ports:
    - "127.0.0.1:9999:8080"
  volumes:
    - /var/run/docker.sock:/var/run/docker.sock:ro
```

Esto es intencionado: los logs pueden contener tokens, errores internos o datos sensibles. No conviene abrir Dozzle directamente a internet sin autenticacion.

## Como desplegarlo en Portainer

1. Entra en Portainer.
2. Ve a `Stacks`.
3. Abre el stack `lcr_robot_varios`.
4. Pulsa `Pull and redeploy` o redepliega desde Git.
5. Cuando termine, debe aparecer un contenedor nuevo:

```text
ausarta-dozzle
```

## Como entrar desde tu PC

Desde tu ordenador, abre una terminal y crea un tunel SSH:

```bash
ssh -L 9999:127.0.0.1:9999 usuario@15.216.15.30
```

Despues abre en el navegador:

```text
http://127.0.0.1:9999
```

Veras todos los contenedores en una sola pantalla, con busqueda y logs en tiempo real.

## Si quieres abrirlo directo por URL publica

No es lo recomendado sin login. Si aun asi lo quieres exponer temporalmente, cambia:

```yaml
ports:
  - "127.0.0.1:9999:8080"
```

por:

```yaml
ports:
  - "9999:8080"
```

y entra en:

```text
http://15.216.15.30:9999
```

Despues cierra el puerto o vuelve a dejarlo en `127.0.0.1`.

## Uso recomendado

- Filtra por `backend` para ver errores de API.
- Filtra por `livekit-agent` para ver si el agente entra en sala, carga prompt o falla STT/TTS.
- Filtra por `arq-worker` para ver webhooks Yeastar, jobs y procesos en segundo plano.
- Busca textos como `ERROR`, `WARNING`, `Yeastar`, `transfer`, `LiveKit`, `webhook`.

## Alternativa mas avanzada

Para historico largo, alertas y graficas se podria montar Grafana + Loki + Promtail. Para empezar, Dozzle es mas rapido y suficiente: no almacena logs en una base externa, solo centraliza la lectura de Docker.
