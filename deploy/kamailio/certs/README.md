# Certificados TLS (puerto 5061)

Coloca aquí:

- `cert.pem` — certificado (cadena completa si aplica)
- `key.pem` — clave privada

Generación rápida (solo pruebas):

```bash
openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 365 -nodes \
  -subj "/CN=sip.ausarta.net"
```

En producción usa Let's Encrypt o el certificado de tu operador SIP.
