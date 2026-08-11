#!/usr/bin/env bash
# =================================================================
# TLSOC Health Collector - server installer
# Run ON the SIEM host (as root):  sudo ./install-health-collector.sh
#
# - installs the collector to /usr/local/bin/tlsoc-health-collector
# - creates the tlsoc-health-* index template in Elasticsearch
# - adds a cron job (every minute) writing to tlsoc-health-YYYY.MM
# =================================================================
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
# default to the repo's own .env; fall back to the /opt install location
DEFAULT_ENV="$(dirname "$HERE")/.env"
[[ -f "$DEFAULT_ENV" ]] || DEFAULT_ENV="/opt/TLSOCDockerDeploy/.env"
ENV_FILE="${ENV_FILE:-$DEFAULT_ENV}"
ES_URL="${ES_URL:-https://localhost:9200}"

if [[ $EUID -ne 0 ]]; then
  echo "Run as root (needs docker access + /etc/cron.d): sudo $0" >&2
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ENV file not found: $ENV_FILE (set ENV_FILE=... if elsewhere)" >&2
  exit 1
fi
# shellcheck disable=SC1090
ELASTIC_PASSWORD="$(grep -E '^ELASTIC_PASSWORD=' "$ENV_FILE" | cut -d= -f2-)"

echo "[1/4] Installing collector -> /usr/local/bin/tlsoc-health-collector"
install -m 0755 "$HERE/tlsoc_health_collector.py" /usr/local/bin/tlsoc-health-collector
mkdir -p /var/lib/tlsoc-health

echo "[2/4] Creating index template tlsoc-health"
curl -sk -u "elastic:${ELASTIC_PASSWORD}" -X PUT \
  "$ES_URL/_index_template/tlsoc-health" \
  -H 'Content-Type: application/json' \
  --data-binary "@$HERE/tlsoc-health-template.json" >/dev/null
echo "      done"

echo "[3/4] Installing cron job /etc/cron.d/tlsoc-health (every minute)"
cat > /etc/cron.d/tlsoc-health <<EOF
# TLSOC SIEM health collector (feeds the SOC Overview dashboard)
* * * * * root flock -n /run/tlsoc-health.lock /usr/local/bin/tlsoc-health-collector --env-file $ENV_FILE >> /var/log/tlsoc-health.log 2>&1
EOF
chmod 0644 /etc/cron.d/tlsoc-health

echo "[4/4] Test run:"
/usr/local/bin/tlsoc-health-collector --env-file "$ENV_FILE"

echo
echo "Installed. Logs: /var/log/tlsoc-health.log"
echo "Data:      $ES_URL  index tlsoc-health-$(date -u +%Y.%m)"
