#!/usr/bin/env bash
set -e

KIBANA_URL="https://kibana:5601"
AUTH="elastic:${ELASTIC_PASSWORD}"

echo "[+] Waiting for Kibana..."
until curl -k -s -u $AUTH "$KIBANA_URL/api/status" >/dev/null; do
  sleep 5
done

echo "[+] Creating TLSOC space (if not exists)"
curl -k -u $AUTH -X POST "$KIBANA_URL/api/spaces/space" \
  -H "kbn-xsrf: true" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "tlsoc",
    "name": "TLSOC",
    "description": "TLSOC Security Operations Center",
    "disabledFeatures": []
  }' || true

echo "[+] Importing TLSOC saved objects"
curl -k -u $AUTH -X POST \
  "$KIBANA_URL/s/tlsoc/api/saved_objects/_import?overwrite=true" \
  -H "kbn-xsrf: true" \
  --form file=@/usr/share/kibana/tlsoc.ndjson

echo "[+] TLSOC bootstrap completed"
