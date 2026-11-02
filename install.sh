#!/usr/bin/env bash
set -e

echo "[+] TLSOC One-Click Installer"

# ---- Prereq checks ----
command -v docker >/dev/null || { echo "Docker missing"; exit 1; }
command -v docker compose >/dev/null || { echo "Docker Compose missing"; exit 1; }

# ---- Env handling ----
if [ ! -f .env ]; then
  echo "[+] Creating .env from template"
  cp .env.example .env
fi

# ---- Resolve HOST_IP ----
AUTO_IP=$(ip route get 8.8.8.8 | awk '{print $7; exit}')
ENV_IP=$(grep "^HOST_IP=" .env | cut -d= -f2)

if [[ -z "$ENV_IP" || "$ENV_IP" == "<IP_OF_THIS_MACHINE>" ]]; then
  echo "[+] Auto-detected HOST_IP: $AUTO_IP"
  sed -i "s|^HOST_IP=.*|HOST_IP=$AUTO_IP|" .env
  HOST_IP=$AUTO_IP
else
  HOST_IP=$ENV_IP
  echo "[+] Using HOST_IP from .env: $HOST_IP"
fi

export HOST_IP

# ---- Kibana encryption key (generated once, kept stable across re-runs) ----
command -v openssl >/dev/null || { echo "openssl missing"; exit 1; }
ENV_KEY=$(grep "^KIBANA_ENCRYPTION_KEY=" .env | cut -d= -f2- || true)

if [[ ${#ENV_KEY} -lt 32 ]]; then
  KIBANA_ENCRYPTION_KEY=$(openssl rand -hex 32)
  if grep -q "^KIBANA_ENCRYPTION_KEY=" .env; then
    sed -i "s|^KIBANA_ENCRYPTION_KEY=.*|KIBANA_ENCRYPTION_KEY=$KIBANA_ENCRYPTION_KEY|" .env
  else
    printf '\nKIBANA_ENCRYPTION_KEY=%s\n' "$KIBANA_ENCRYPTION_KEY" >> .env
  fi
  echo "[+] Generated KIBANA_ENCRYPTION_KEY and saved it to .env"
else
  echo "[+] Using KIBANA_ENCRYPTION_KEY from .env"
fi

# ---- Generate certificates ----
chmod +x certs/generate-certs.sh
./certs/generate-certs.sh "$HOST_IP"

# ---- Permissions fix (Kibana TLS issue) ----
find certs -type f -exec chmod 644 {} \;

# ---- Start stack ----
docker compose up -d

# ---- Health monitoring + SOC Overview dashboard (automatic, best effort) ----
# On a FRESH install this will stop early because the elastic password is not
# set yet: finish the first-time password steps in the README, then run
#   sudo ./monitoring/setup-monitoring.sh
if [ -f monitoring/setup-monitoring.sh ]; then
  chmod +x monitoring/*.sh monitoring/tlsoc_health_collector.py
  echo "[+] Setting up health monitoring + SOC Overview dashboard"
  if ! ENV_FILE="$(pwd)/.env" ./monitoring/setup-monitoring.sh; then
    echo "[!] Monitoring setup not finished yet (normal on first install)."
    echo "    After the password steps, run: sudo ./monitoring/setup-monitoring.sh"
  fi
fi

echo "--------------------------------------"
echo " Kibana: https://$HOST_IP:5601"
echo " User: elastic"
echo "--------------------------------------"

