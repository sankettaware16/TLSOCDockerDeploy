#!/usr/bin/env bash
# =================================================================
# TLSOC Monitoring - one-shot automatic setup
#
#   sudo ./monitoring/setup-monitoring.sh
#
# Does everything needed for the "TLSOC - SOC Overview" dashboard:
#   1. waits for Elasticsearch + Kibana to answer
#   2. installs the tlsoc-health index template
#   3. installs the health collector + per-minute cron job
#   4. imports the SOC Overview dashboard into Kibana
#
# Called automatically at the end of install.sh (best effort - on a
# fresh install it will ask you to re-run it once passwords are set).
#
# Env overrides:
#   ENV_FILE      path to the stack .env       (default: <repo>/.env)
#   ES_URL        default https://localhost:9200
#   KIBANA_URL    default https://localhost:5601
#   KIBANA_SPACE  Kibana space id for the dashboard (default: default)
# =================================================================
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"
ENV_FILE="${ENV_FILE:-$REPO/.env}"
ES_URL="${ES_URL:-https://localhost:9200}"
KIBANA_URL="${KIBANA_URL:-https://localhost:5601}"
KIBANA_SPACE="${KIBANA_SPACE:-default}"

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi
if [[ ! -f "$ENV_FILE" ]]; then
  echo "[monitoring] .env not found at $ENV_FILE (set ENV_FILE=...)" >&2
  exit 1
fi
ELASTIC_PASSWORD="$(grep -E '^ELASTIC_PASSWORD=' "$ENV_FILE" | cut -d= -f2-)"

es() { curl -sk -u "elastic:${ELASTIC_PASSWORD}" "$@"; }

echo "[monitoring] 1/4 waiting for Elasticsearch at $ES_URL"
for i in $(seq 1 30); do
  status="$(es -o /dev/null -w '%{http_code}' "$ES_URL" || true)"
  [[ "$status" == "200" ]] && break
  if [[ "$status" == "401" ]]; then
    echo "[monitoring] Elasticsearch rejected the password in $ENV_FILE."
    echo "             Finish the first-time password steps in the README,"
    echo "             then re-run: sudo ./monitoring/setup-monitoring.sh"
    exit 2
  fi
  sleep 4
done
if [[ "${status:-}" != "200" ]]; then
  echo "[monitoring] Elasticsearch did not come up - re-run this script later." >&2
  exit 2
fi

echo "[monitoring] 2/4 index template + health collector (cron)"
ENV_FILE="$ENV_FILE" ES_URL="$ES_URL" "$HERE/install-health-collector.sh"

echo "[monitoring] 3/4 waiting for Kibana at $KIBANA_URL"
for i in $(seq 1 45); do
  kstatus="$(es -o /dev/null -w '%{http_code}' "$KIBANA_URL/api/status" || true)"
  [[ "$kstatus" == "200" ]] && break
  sleep 4
done
if [[ "${kstatus:-}" != "200" ]]; then
  echo "[monitoring] Kibana not ready - dashboard not imported. Re-run later." >&2
  exit 2
fi

echo "[monitoring] 4/4 importing SOC Overview dashboard (space: $KIBANA_SPACE)"
NDJSON="$REPO/kibana/saved_objects/tlsoc_overview_dashboard.ndjson"
if command -v python3 >/dev/null && [[ "$KIBANA_SPACE" != "default" ]]; then
  # regenerate so the alert panels read this space's detection-alert index
  NDJSON="$(mktemp /tmp/tlsoc_overview.XXXX.ndjson)"
  python3 "$REPO/kibana/generate_overview_dashboard.py" \
    --space "$KIBANA_SPACE" --out "$NDJSON" >/dev/null
fi
SPACE_PATH=""
[[ "$KIBANA_SPACE" != "default" ]] && SPACE_PATH="/s/$KIBANA_SPACE"
result="$(es -X POST \
  "$KIBANA_URL$SPACE_PATH/api/saved_objects/_import?overwrite=true" \
  -H "kbn-xsrf: true" --form file=@"$NDJSON")"
if echo "$result" | grep -q '"success":true'; then
  echo "[monitoring] done - open $KIBANA_URL$SPACE_PATH/app/dashboards (TLSOC - SOC Overview)"
else
  echo "[monitoring] dashboard import FAILED: ${result:0:300}" >&2
  exit 2
fi
