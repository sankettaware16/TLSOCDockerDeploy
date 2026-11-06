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
chmod 600 .env

command -v openssl >/dev/null || { echo "openssl missing"; exit 1; }

# Set KEY=value in .env, replacing an existing line or appending a new one.
set_env() {
  if grep -q "^$1=" .env; then
    sed -i "s|^$1=.*|$1=$2|" .env
  else
    printf '\n%s=%s\n' "$1" "$2" >> .env
  fi
}
get_env() { grep "^$1=" .env | head -1 | cut -d= -f2- || true; }

# ---- Passwords (generated once; never overwrite a stack that is already initialised) ----
# The template ships placeholder passwords. Replace them with random ones, but
# only while Elasticsearch has no data volume yet: after first start the
# password lives inside Elasticsearch and .env must keep matching it.
GENERATED_PASSWORD=""
if docker volume ls -q | grep -q '_esdata$'; then
  STACK_INITIALISED=yes
else
  STACK_INITIALISED=no
fi
for var in ELASTIC_PASSWORD KIBANA_PASSWORD; do
  value=$(get_env "$var")
  if [[ -z "$value" || "$value" == ChangeMe* ]]; then
    if [[ "$STACK_INITIALISED" == yes ]]; then
      echo "[!] $var in .env is a placeholder but Elasticsearch is already initialised."
      echo "    Set the real password in .env (see docs/installation.md) and re-run."
      exit 1
    fi
    set_env "$var" "$(openssl rand -hex 16)"
    echo "[+] Generated $var and saved it to .env"
    [[ "$var" == ELASTIC_PASSWORD ]] && GENERATED_PASSWORD=yes
  fi
done
ELASTIC_PASSWORD=$(get_env ELASTIC_PASSWORD)
KIBANA_PASSWORD=$(get_env KIBANA_PASSWORD)
KIBANA_ENCRYPTION_KEY=$(get_env KIBANA_ENCRYPTION_KEY)

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
if [[ ${#KIBANA_ENCRYPTION_KEY} -lt 32 ]]; then
  KIBANA_ENCRYPTION_KEY=$(openssl rand -hex 32)
  set_env KIBANA_ENCRYPTION_KEY "$KIBANA_ENCRYPTION_KEY"
  echo "[+] Generated KIBANA_ENCRYPTION_KEY and saved it to .env"
else
  echo "[+] Using KIBANA_ENCRYPTION_KEY from .env"
fi
export KIBANA_ENCRYPTION_KEY

# ---- Certificates ----
# Generated on a first install or when the server IP changed. An existing,
# still-valid set is kept, so re-running this installer never replaces the CA
# under a running stack.
chmod +x certs/generate-certs.sh
if [ -f certs/ca/ca.crt ] && [ -f certs/elasticsearch/elasticsearch.crt ] \
   && openssl x509 -in certs/elasticsearch/elasticsearch.crt -noout -ext subjectAltName 2>/dev/null \
        | grep -q "IP Address:$HOST_IP" \
   && openssl x509 -in certs/elasticsearch/elasticsearch.crt -noout -checkend 2592000 >/dev/null 2>&1; then
  echo "[+] Keeping existing certificates (valid for $HOST_IP)"
else
  ./certs/generate-certs.sh "$HOST_IP"
fi

# ---- Permissions fix (Kibana TLS issue) ----
find certs -type f -exec chmod 644 {} \; 2>/dev/null || true

# ---- Start Elasticsearch first ----
# Retention policies and field mappings must exist BEFORE the first event is
# indexed (the first document otherwise decides each field's type), so the
# rest of the stack starts only after they are in place.
echo "[+] Starting Elasticsearch"
docker compose up -d elasticsearch

ES_URL="https://localhost:9200"
es_curl() { curl -sk -u "elastic:${ELASTIC_PASSWORD}" "$@"; }

echo -n "[+] Waiting for Elasticsearch "
code=000
for i in $(seq 1 60); do
  code=$(es_curl -o /dev/null -w '%{http_code}' "$ES_URL" || true)
  [[ "$code" == 200 || "$code" == 401 ]] && break
  echo -n "."; sleep 3
done
echo
if [[ "$code" != 200 ]]; then
  echo "[!] Elasticsearch is not accepting the password in .env (HTTP $code)."
  echo "    Check 'docker logs elasticsearch', then re-run ./install.sh."
  exit 1
fi

# kibana_system is Kibana's service account. Setting its password here removes
# the old manual reset step: Kibana starts already able to connect.
es_curl -X POST "$ES_URL/_security/user/kibana_system/_password" \
  -H 'Content-Type: application/json' \
  -d "{\"password\":\"${KIBANA_PASSWORD}\"}" >/dev/null
echo "[+] kibana_system password set"

# ---- Data retention + index templates ----
python3 elasticsearch/setup_storage.py --es-url "$ES_URL"

# ---- Start the rest of the stack ----
docker compose up -d

# ---- Kafka topics: one per log source (tlsoc.logs.<source>) ----
# Nothing is created in advance: each source's topic appears with its first
# line. The cron job gives busy sources their partitions (kafka/topics.conf).
chmod +x kafka/setup-topics.sh
./kafka/setup-topics.sh --wait 180 --install-cron || echo "[!] Kafka topic tuning not set up yet - run: sudo ./kafka/setup-topics.sh --install-cron (sources still create their own topics)"

# ---- Dashboards + health monitoring ----
# dashboards.sh waits for Kibana, imports the SOC Overview dashboard and (as
# root) installs the health collector. If anything is not ready in time it
# schedules automatic retries (as root) - or tells you the one command to run.
chmod +x dashboards.sh monitoring/*.sh monitoring/tlsoc_health_collector.py elasticsearch/*.py
./dashboards.sh --from-install --wait 300 || true

echo "--------------------------------------"
echo " Kibana:   https://$HOST_IP:$(get_env KIBANA_PORT | grep . || echo 5601)"
echo " User:     elastic"
if [[ -n "$GENERATED_PASSWORD" ]]; then
  echo " Password: $ELASTIC_PASSWORD   (also stored in .env)"
else
  echo " Password: see ELASTIC_PASSWORD in .env"
fi
echo " Sources:  one Kafka topic per source (tlsoc.logs.<source>); onboard servers with tlsoc-onboard.sh"
echo " Retention: logs $(get_env LOG_RETENTION_DAYS | grep . || echo 180) days (change in .env; see docs/retention-and-storage.md)"
echo "--------------------------------------"
