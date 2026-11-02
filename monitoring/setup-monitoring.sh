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
WAIT_SECONDS="${WAIT_SECONDS:-180}"          # how long to wait for ES and for Kibana
SKIP_COLLECTOR="${SKIP_COLLECTOR:-}"         # non-empty: dashboards only, no root needed
ES_TRIES=$(( WAIT_SECONDS / 4 + 1 ))

if [[ -z "$SKIP_COLLECTOR" && $EUID -ne 0 ]]; then
  echo "Run as root: sudo $0   (or set SKIP_COLLECTOR=1 to import the dashboard only)" >&2
  exit 1
fi
if [[ ! -f "$ENV_FILE" ]]; then
  echo "[monitoring] .env not found at $ENV_FILE (set ENV_FILE=...)" >&2
  exit 1
fi
ELASTIC_PASSWORD="$(grep -E '^ELASTIC_PASSWORD=' "$ENV_FILE" | cut -d= -f2-)"

es() { curl -sk -u "elastic:${ELASTIC_PASSWORD}" "$@"; }

echo "[monitoring] 1/4 waiting for Elasticsearch at $ES_URL"
for i in $(seq 1 "$ES_TRIES"); do
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

# The health data's retention policy must exist before its template references
# it. install.sh creates it; do it here too so this script also works alone
# (for example on a stack installed before retention policies existed).
if [[ "$(es -o /dev/null -w '%{http_code}' "$ES_URL/_ilm/policy/tlsoc-health" || true)" == "404" ]] \
   && command -v python3 >/dev/null; then
  echo "[monitoring] creating retention policies + templates first"
  python3 "$REPO/elasticsearch/setup_storage.py" --env-file "$ENV_FILE" --es-url "$ES_URL" \
    || echo "[monitoring] WARN: storage setup failed - run elasticsearch/setup_storage.py"
fi

if [[ -n "$SKIP_COLLECTOR" ]]; then
  echo "[monitoring] 2/4 health collector skipped (SKIP_COLLECTOR set) - run as root to install it"
else
  echo "[monitoring] 2/4 index template + health collector (cron)"
  ENV_FILE="$ENV_FILE" ES_URL="$ES_URL" "$HERE/install-health-collector.sh"
fi

echo "[monitoring] 3/4 waiting for Kibana at $KIBANA_URL"
for i in $(seq 1 "$ES_TRIES"); do
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
if [[ "$KIBANA_SPACE" != "default" ]]; then
  SPACE_PATH="/s/$KIBANA_SPACE"
  # the import fails if the space does not exist yet
  if [[ "$(es -o /dev/null -w '%{http_code}' "$KIBANA_URL/api/spaces/space/$KIBANA_SPACE")" == "404" ]]; then
    es -X POST "$KIBANA_URL/api/spaces/space" -H "kbn-xsrf: true" -H 'Content-Type: application/json' \
      -d "{\"id\":\"$KIBANA_SPACE\",\"name\":\"$KIBANA_SPACE\"}" >/dev/null
    echo "[monitoring] created Kibana space $KIBANA_SPACE"
  fi
fi
result="$(es -X POST \
  "$KIBANA_URL$SPACE_PATH/api/saved_objects/_import?overwrite=true" \
  -H "kbn-xsrf: true" --form file=@"$NDJSON")"
if echo "$result" | grep -q '"success":true'; then
  # The alert panels read the Security detection-alerts index. It is normally
  # created the first time the Security app is opened; create it now so those
  # panels work from the start (best effort - safe to repeat).
  es -X POST "$KIBANA_URL$SPACE_PATH/api/detection_engine/index" \
    -H "kbn-xsrf: true" >/dev/null 2>&1 || true
  # The collector's first run (step 2) happens while Kibana is still booting.
  # Take one more reading now that everything is up, so the dashboard opens on
  # the settled state instead of waiting for the next cron run.
  if [[ -x /usr/local/bin/tlsoc-health-collector ]]; then
    /usr/local/bin/tlsoc-health-collector --env-file "$ENV_FILE" >/dev/null 2>&1 || true
  fi
  echo "[monitoring] done - open $KIBANA_URL$SPACE_PATH/app/dashboards (TLSOC - SOC Overview)"
else
  echo "[monitoring] dashboard import FAILED: ${result:0:300}" >&2
  exit 2
fi
