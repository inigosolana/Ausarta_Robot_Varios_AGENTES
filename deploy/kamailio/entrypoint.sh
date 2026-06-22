#!/bin/sh
# Carga trusted_peers + region_peers en ipops, genera dispatcher.list y arranca Kamailio.
set -eu

CFG=/etc/kamailio/kamailio.cfg
PEERS_FILE=/etc/kamailio/trusted_peers.list
REGION_PEERS_FILE=/etc/kamailio/region_peers.list
DISPATCHER_FILE=/etc/kamailio/dispatcher.list
RENDER_SCRIPT=/etc/kamailio/render_dispatcher.sh

load_ipops_group() {
  group="$1"
  file="$2"
  [ -f "$file" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      ''|\#*) continue ;;
    esac
    addr=$(echo "$line" | cut -d/ -f1)
    mask=$(echo "$line" | cut -s -d/ -f2)
    if [ -z "$mask" ]; then
      mask=32
    fi
    kamcmd ipops.add_ip "$group" "$addr" "$mask" 2>/dev/null || \
      echo "warn: could not add $group peer $addr/$mask" >&2
  done < "$file"
}

# Añadir CIDRs extra desde variable de entorno (Portainer)
if [ -n "${SIP_TRUSTED_CIDRS:-}" ]; then
  echo "# from SIP_TRUSTED_CIDRS env" >> "$PEERS_FILE"
  echo "$SIP_TRUSTED_CIDRS" | tr ',' '\n' >> "$PEERS_FILE"
fi

# Latam carriers adicionales vía env (coma-separado)
if [ -n "${SIP_LATAM_CIDRS:-}" ]; then
  echo "# from SIP_LATAM_CIDRS env" >> "$REGION_PEERS_FILE"
  echo "$SIP_LATAM_CIDRS" | tr ',' '\n' >> "$REGION_PEERS_FILE"
fi

# Generar dispatcher.list (env LIVEKIT_EDGE_* o plantilla estática)
if [ -x "$RENDER_SCRIPT" ]; then
  DISPATCHER_STATIC_FILE=/etc/kamailio/dispatcher.list.example \
    "$RENDER_SCRIPT" > "$DISPATCHER_FILE"
  echo "kamailio: dispatcher.list generated ($(wc -l < "$DISPATCHER_FILE") lines)"
else
  echo "warn: render_dispatcher.sh not found, using mounted dispatcher.list" >&2
fi

# Kamailio en background para poder usar kamcmd
kamailio -f "$CFG" -E -DD "$@" &
KAM_PID=$!

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

# Grupos ipops — TRUSTED_SOURCE + enrutamiento regional
load_ipops_group trusted "$PEERS_FILE"
load_ipops_group carrier_latam "$REGION_PEERS_FILE"

echo "kamailio: trusted peers loaded from $PEERS_FILE"
echo "kamailio: latam region peers loaded from $REGION_PEERS_FILE"

wait "$KAM_PID"
