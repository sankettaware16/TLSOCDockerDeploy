#!/usr/bin/env bash
set -e

echo "[+] TLSOC One-Click Installer"

command -v docker >/dev/null || { echo "Docker missing"; exit 1; }

if [ ! -f .env ]; then
  cp .env.example .env
fi

HOST_IP=$(ip route get 8.8.8.8 | awk '{print $7; exit}')
echo "[+] Host IP: $HOST_IP"

chmod +x certs/generate-certs.sh
./certs/generate-certs.sh "$HOST_IP"

docker compose up -d

echo "--------------------------------------"
echo " Kibana: https://$HOST_IP:5601"
echo " User: elastic"
echo "--------------------------------------"
