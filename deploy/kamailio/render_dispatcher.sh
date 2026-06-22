#!/bin/sh
# Genera dispatcher.list desde variables de entorno (Easypanel / Portainer).
# Si no hay LIVEKIT_EDGE_MADRID_HOST, imprime el fichero estático de ejemplo.
set -eu

STATIC_FILE="${DISPATCHER_STATIC_FILE:-/etc/kamailio/dispatcher.list.example}"
MADRID_HOST="${LIVEKIT_EDGE_MADRID_HOST:-}"
LATAM_HOST="${LIVEKIT_EDGE_LATAM_HOST:-}"
MADRID_BACKUP_HOST="${LIVEKIT_EDGE_MADRID_BACKUP_HOST:-}"
MADRID_PORT="${LIVEKIT_EDGE_MADRID_PORT:-5060}"
LATAM_PORT="${LIVEKIT_EDGE_LATAM_PORT:-5060}"
MADRID_BACKUP_PORT="${LIVEKIT_EDGE_MADRID_BACKUP_PORT:-5060}"
MADRID_WEIGHT="${LIVEKIT_EDGE_MADRID_WEIGHT:-80}"
LATAM_WEIGHT="${LIVEKIT_EDGE_LATAM_WEIGHT:-70}"
MADRID_BACKUP_WEIGHT="${LIVEKIT_EDGE_MADRID_BACKUP_WEIGHT:-40}"

if [ -z "$MADRID_HOST" ] && [ -z "$LATAM_HOST" ]; then
  if [ -f "$STATIC_FILE" ]; then
    cat "$STATIC_FILE"
    exit 0
  fi
  echo "error: no LIVEKIT_EDGE_* hosts and no static dispatcher file" >&2
  exit 1
fi

cat <<EOF
# Generated at container start — do not edit manually
EOF

if [ -n "$MADRID_HOST" ]; then
  printf '1 sip:%s:%s 0 %s region=eu;site=edge-madrid;role=primary\n' \
    "$MADRID_HOST" "$MADRID_PORT" "$MADRID_WEIGHT"
fi

if [ -n "$LATAM_HOST" ]; then
  printf '1 sip:%s:%s 0 %s region=latam;site=edge-latam;role=primary\n' \
    "$LATAM_HOST" "$LATAM_PORT" "$LATAM_WEIGHT"
fi

if [ -n "$MADRID_BACKUP_HOST" ]; then
  printf '1 sip:%s:%s 0 %s region=eu;site=edge-madrid;role=backup\n' \
    "$MADRID_BACKUP_HOST" "$MADRID_BACKUP_PORT" "$MADRID_BACKUP_WEIGHT"
fi
