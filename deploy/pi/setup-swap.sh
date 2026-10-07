#!/usr/bin/env bash
# Add 2GB swap — empfohlen auf Raspberry Pi 3B (1GB RAM).
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Bitte mit sudo ausführen."
  exit 1
fi

SWAPFILE=/var/swap.apofika
SIZE_MB=2048

if [[ -f "$SWAPFILE" ]]; then
  echo "Swapfile existiert bereits: $SWAPFILE"
else
  echo "Lege ${SIZE_MB}MB Swap an…"
  dd if=/dev/zero of="$SWAPFILE" bs=1M count="$SIZE_MB" status=progress
  chmod 600 "$SWAPFILE"
  mkswap "$SWAPFILE"
fi

if ! grep -q "$SWAPFILE" /etc/fstab; then
  echo "$SWAPFILE none swap sw 0 0" >> /etc/fstab
fi

swapon "$SWAPFILE" || true
swapon --show
free -h
