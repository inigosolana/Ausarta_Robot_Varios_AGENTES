#!/bin/sh
# Carga trusted_peers.list + SIP_TRUSTED_CIDRS en ipops antes de aceptar tráfico.
set -eu

CFG=/etc/kamailio/kamailio.cfg
PEERS_FILE=/etc/kamailio/trusted_peers.list

# Añadir CIDRs extra desde variable de entorno (Portainer)
if [ -n "${SIP_TRUSTED_CIDRS:-}" ]; then
  echo "# from SIP_TRUSTED_CIDRS env" >> "$PEERS_FILE"
  echo "$SIP_TRUSTED_CIDRS" | tr ',' '\n' >> "$PEERS_FILE"
fi

# Kamailio en background para poder usar kamcmd
kamailio -f "$CFG" -E -DD "$@" &
KAM_PID=$!

# Esperar a que el ctl socket esté listo
TRIES=0
until kamcmd core.ps 2>/dev/null | grep -q "kamailio"; do
  TRIES=$((TRIES + 1))
  if [ "$TRIES" -ge 30 ]; then
    echo "kamailio ctl socket not ready" >&2
    kill "$KAM_PID" 2>/dev/null || true
    exit 1
  fi
  sleep 0.2
done

# Grupo ipops "trusted" — usado en kamailio.cfg route TRUSTED_SOURCE
if [ -f "$PEERS_FILE" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      ''|\#*) continue ;;
    esac
    addr=$(echo "$line" | cut -d/ -f1)
    mask=$(echo "$line" | cut -s -d/ -f2)
    if [ -z "$mask" ]; then
      mask=32
    fi
    kamcmd ipops.add_ip trusted "$addr" "$mask" 2>/dev/null || \
      echo "warn: could not add trusted peer $addr/$mask" >&2
  done < "$PEERS_FILE"
fi

echo "kamailio: trusted peers loaded from $PEERS_FILE"

wait "$KAM_PID"
