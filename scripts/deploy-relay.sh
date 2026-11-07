#!/usr/bin/env bash
set -euo pipefail

BUILD_DIR="${1:-build}"
ENV_FILE="${ENV_FILE:-agent-input.env}"

if [ ! -f "$ENV_FILE" ]; then
  echo "missing $ENV_FILE" >&2
  exit 2
fi

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

if [ ! -f "$BUILD_DIR/sing-box/config.json" ]; then
  echo "missing $BUILD_DIR/sing-box/config.json; run tools/render-config.py first" >&2
  exit 2
fi

: "${RELAY_SSH_TARGET:?missing RELAY_SSH_TARGET}"
: "${RELAY_SING_BOX_CONFIG_PATH:?missing RELAY_SING_BOX_CONFIG_PATH}"
: "${RELAY_SING_BOX_SERVICE:?missing RELAY_SING_BOX_SERVICE}"

REMOTE_TMP="/tmp/agent-route-kit-sing-box.json"

scp "$BUILD_DIR/sing-box/config.json" "$RELAY_SSH_TARGET:$REMOTE_TMP"
ssh "$RELAY_SSH_TARGET" "
  set -e
  sudo mkdir -p /etc/sing-box/cert
  if [ ! -f /etc/sing-box/cert/cert.pem ] || [ ! -f /etc/sing-box/cert/key.pem ]; then
    sudo openssl req -x509 -newkey rsa:2048 -nodes \
      -keyout /etc/sing-box/cert/key.pem \
      -out /etc/sing-box/cert/cert.pem \
      -days 3650 \
      -subj '/CN=${HY2_SNI}'
    sudo chmod 600 /etc/sing-box/cert/key.pem
  fi
  sudo install -m 600 -o root -g root '$REMOTE_TMP' '$RELAY_SING_BOX_CONFIG_PATH'
  if command -v sing-box >/dev/null 2>&1; then
    sudo sing-box check -c '$RELAY_SING_BOX_CONFIG_PATH'
  fi
  # Optional: configure firewall rules for port hopping & reality if ufw is available and active
  if command -v ufw >/dev/null 2>&1 && sudo ufw status | grep -q "Status: active"; then
    if [ -n "${REALITY_PORT:-}" ]; then
      sudo ufw allow "${REALITY_PORT}/tcp" comment "VLESS-Reality" >/dev/null 2>&1 || true
    fi
    if [ -n "${HY2_PORTS:-}" ]; then
      sudo ufw allow "${HY2_PORTS}/udp" comment "Hysteria2 Port Hopping" >/dev/null 2>&1 || true
      if [ -f /etc/ufw/before.rules ] && ! grep -q "\*nat" /etc/ufw/before.rules; then
        sudo sed -i '1i # NAT table for Hysteria2 port hopping\n*nat\n:PREROUTING ACCEPT [0:0]\n-A PREROUTING -p udp --dport '"${HY2_PORTS}"' -j REDIRECT --to-ports '"${AI_RELAY_PORT}"'\nCOMMIT\n' /etc/ufw/before.rules
        sudo ufw reload >/dev/null 2>&1 || true
      fi
    fi
  fi
  sudo systemctl restart '$RELAY_SING_BOX_SERVICE'
  sudo systemctl is-active '$RELAY_SING_BOX_SERVICE'
"

echo "relay deployed and service is active"
