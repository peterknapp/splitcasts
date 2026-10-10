#!/usr/bin/env bash
# Run on the Pi after: cloudflared tunnel login
set -euo pipefail

export PATH="$HOME/.local/bin:$PATH"
DOMAIN="${DOMAIN:-splitcasts.peterknapp.de}"
TUNNEL_NAME="${TUNNEL_NAME:-splitcasts}"
CONFIG_DIR="$HOME/.cloudflared"
CONFIG_FILE="$CONFIG_DIR/config.yml"
REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"

if [[ ! -x "$HOME/.local/bin/cloudflared" ]]; then
  echo "cloudflared fehlt in ~/.local/bin"
  exit 1
fi

if [[ ! -f "$CONFIG_DIR/cert.pem" ]]; then
  echo "Zuerst im Browser anmelden:"
  echo "  cloudflared tunnel login"
  exit 1
fi

if ! cloudflared tunnel list 2>/dev/null | grep -q "$TUNNEL_NAME"; then
  echo "Erstelle Tunnel $TUNNEL_NAME …"
  cloudflared tunnel create "$TUNNEL_NAME"
else
  echo "Tunnel $TUNNEL_NAME existiert bereits."
fi

TUNNEL_UUID="$(cloudflared tunnel list | awk -v n="$TUNNEL_NAME" '$2==n {print $1; exit}')"
if [[ -z "$TUNNEL_UUID" ]]; then
  echo "Konnte Tunnel-UUID nicht ermitteln."
  cloudflared tunnel list
  exit 1
fi
echo "Tunnel UUID: $TUNNEL_UUID"

CRED="$CONFIG_DIR/$TUNNEL_UUID.json"
if [[ ! -f "$CRED" ]]; then
  echo "Credentials fehlen: $CRED"
  exit 1
fi

cat > "$CONFIG_FILE" <<EOF
tunnel: $TUNNEL_UUID
credentials-file: $CRED

ingress:
  - hostname: $DOMAIN
    service: http://127.0.0.1:8787
  - service: http_status:404
EOF
echo "Wrote $CONFIG_FILE"

echo "DNS-Route setzen …"
cloudflared tunnel route dns "$TUNNEL_NAME" "$DOMAIN"

# Update /etc/apofika.env if writable via sudo
PUBLIC_BASE="https://$DOMAIN"
if [[ -f /etc/apofika.env ]]; then
  if sudo -n true 2>/dev/null; then
    sudo sed -i "s|^APOFIKA_PUBLIC_BASE=.*|APOFIKA_PUBLIC_BASE=$PUBLIC_BASE|" /etc/apofika.env
    echo "Updated /etc/apofika.env → $PUBLIC_BASE"
  else
    echo "Bitte manuell in /etc/apofika.env setzen:"
    echo "  APOFIKA_PUBLIC_BASE=$PUBLIC_BASE"
    echo "  sudo nano /etc/apofika.env"
  fi
fi

# Install systemd unit (needs sudo)
UNIT_SRC="$REPO_DIR/deploy/pi/cloudflared.service"
if [[ -f "$UNIT_SRC" ]]; then
  if sudo -n true 2>/dev/null; then
    sudo cp "$UNIT_SRC" /etc/systemd/system/cloudflared-splitcasts.service
    sudo systemctl daemon-reload
    sudo systemctl enable --now cloudflared-splitcasts.service
    systemctl --no-pager --full status cloudflared-splitcasts.service | sed -n '1,15p'
  else
    echo "Systemd-Unit installieren mit:"
    echo "  sudo cp $UNIT_SRC /etc/systemd/system/cloudflared-splitcasts.service"
    echo "  sudo systemctl daemon-reload"
    echo "  sudo systemctl enable --now cloudflared-splitcasts.service"
  fi
fi

echo
echo "Feed neu schreiben:"
echo "  cd $REPO_DIR && .venv/bin/apofika process --force --public-base $PUBLIC_BASE"
echo
echo "Overcast-URL: $PUBLIC_BASE/feed.xml"
