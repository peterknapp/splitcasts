#!/usr/bin/env bash
# Install ApoFiKa systemd units on a Raspberry Pi.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ENV_FILE=/etc/apofika.env
SERVICE_USER="${SUDO_USER:-${USER}}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Bitte mit sudo ausführen: sudo bash deploy/pi/install.sh"
  exit 1
fi

if [[ ! -x "$ROOT/.venv/bin/apofika" ]]; then
  echo "Fehlt: $ROOT/.venv/bin/apofika"
  echo "Zuerst: python3 -m venv .venv && .venv/bin/pip install -e ."
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  sed "s|/home/pi/ApoFiKaSplit|$ROOT|g" "$ROOT/deploy/pi/apofika.env.example" > "$ENV_FILE"
  # Replace default user path already done; keep host/port defaults
  echo "Created $ENV_FILE — bitte APOFIKA_PUBLIC_BASE anpassen."
else
  echo "Keeping existing $ENV_FILE"
fi

# Rewrite units with concrete user + paths (EnvironmentFile expansion is unreliable for User=)
for unit in apofika-serve.service apofika-process.service apofika-process.timer; do
  sed \
    -e "s|User=pi|User=$SERVICE_USER|g" \
    -e "s|Group=pi|Group=$SERVICE_USER|g" \
    "$ROOT/deploy/pi/$unit" > "/etc/systemd/system/$unit"
done

systemctl daemon-reload
systemctl enable --now apofika-serve.service
systemctl enable --now apofika-process.timer

echo
echo "Aktiv:"
systemctl --no-pager --full status apofika-serve.service | sed -n '1,12p' || true
systemctl --no-pager list-timers apofika-process.timer || true
echo
echo "Manueller Test: sudo systemctl start apofika-process.service"
echo "Logs: journalctl -u apofika-process.service -u apofika-serve.service -f"
