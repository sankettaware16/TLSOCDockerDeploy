#!/bin/bash
# =============================================================================
# TLSOC Auto-Setup Script
# =============================================================================
# This script runs once when the 'setup' container starts.
# It automates the Elasticsearch password configuration and imports the Kibana
# dashboards and SIEM rules automatically.

set -e

echo "=========================================================="
echo "⏳ Waiting for Elasticsearch to become available..."
echo "=========================================================="

until curl -s --cacert /usr/share/elasticsearch/config/certs/ca/ca.crt -u elastic:${ELASTIC_PASSWORD} https://elasticsearch:9200 | grep -q "missing authentication credentials"; do
  # Actually, if we pass the password, it will return JSON with the cluster info.
  if curl -s --cacert /usr/share/elasticsearch/config/certs/ca/ca.crt -u elastic:${ELASTIC_PASSWORD} https://elasticsearch:9200 | grep -q "cluster_name"; then
    break
  fi
  sleep 5
done

echo "✅ Elasticsearch is up!"

echo "=========================================================="
echo "🔐 Setting Kibana System User Password..."
echo "=========================================================="
curl -s -X POST -u elastic:${ELASTIC_PASSWORD} -H "Content-Type: application/json" \
  https://elasticsearch:9200/_security/user/kibana_system/_password \
  -d "{\"password\":\"${KIBANA_PASSWORD}\"}" \
  --cacert /usr/share/elasticsearch/config/certs/ca/ca.crt

echo -e "\n✅ Kibana System password set successfully!"

echo "=========================================================="
echo "⏳ Waiting for Kibana to become available..."
echo "=========================================================="
# Wait for Kibana API to be ready
until curl -s -I -u elastic:${ELASTIC_PASSWORD} --cacert /usr/share/elasticsearch/config/certs/ca/ca.crt https://kibana:5601/api/status | grep -q "HTTP/1.1 200"; do
  sleep 5
done

echo "✅ Kibana is up!"

echo "=========================================================="
echo "🌌 Creating TLSOC Space..."
echo "=========================================================="

B64_IMAGE=""
if [ -f "/setup/logo.png" ]; then
  echo "Found logo.png, attaching to Space..."
  B64_IMAGE="data:image/png;base64,$(base64 -w 0 /setup/logo.png)"
fi

curl -s -X POST "https://kibana:5601/api/spaces/space" \
  -H "kbn-xsrf: true" \
  -H "Content-Type: application/json" \
  -u elastic:${ELASTIC_PASSWORD} \
  --cacert /usr/share/elasticsearch/config/certs/ca/ca.crt \
  -d "{\"id\":\"tlsoc\",\"name\":\"TLSOC\",\"description\":\"\",\"color\":\"#6092C0\",\"imageUrl\":\"${B64_IMAGE}\"}"

echo -e "\n✅ Space created successfully!"

echo "=========================================================="
echo "📊 Creating Required Data Views..."
echo "=========================================================="
curl -s -X POST "https://kibana:5601/s/tlsoc/api/data_views/data_view" \
  -H "kbn-xsrf: true" \
  -H "Content-Type: application/json" \
  -u elastic:${ELASTIC_PASSWORD} \
  --cacert /usr/share/elasticsearch/config/certs/ca/ca.crt \
  -d "{\"data_view\":{\"title\":\"fosstlsoc-logs-*\",\"name\":\"SIEM Rule View 1\",\"id\":\"4ea16e42-92a0-4495-a6c1-a1848eb235f6\"}}"

curl -s -X POST "https://kibana:5601/s/tlsoc/api/data_views/data_view" \
  -H "kbn-xsrf: true" \
  -H "Content-Type: application/json" \
  -u elastic:${ELASTIC_PASSWORD} \
  --cacert /usr/share/elasticsearch/config/certs/ca/ca.crt \
  -d "{\"data_view\":{\"title\":\"fosstlsoc-logs-*\",\"name\":\"SIEM Rule View 2\",\"id\":\"60b3f25a-9745-44fb-95c8-f1b5e8c5b3c8\"}}"

echo -e "\n✅ Required Data Views created!"

echo "=========================================================="
echo "📥 Importing Dashboards & Saved Objects..."
echo "=========================================================="
curl -s -X POST "https://kibana:5601/s/tlsoc/api/saved_objects/_import?overwrite=true" \
  -H "kbn-xsrf: true" \
  -u elastic:${ELASTIC_PASSWORD} \
  --form file=@/setup/dashboards.ndjson \
  --cacert /usr/share/elasticsearch/config/certs/ca/ca.crt

echo -e "\n✅ Dashboards imported successfully!"

echo "=========================================================="
echo "📥 Importing SIEM Detection Rules..."
echo "=========================================================="
curl -s -X POST "https://kibana:5601/s/tlsoc/api/detection_engine/rules/_import?overwrite=true" \
  -H "kbn-xsrf: true" \
  -u elastic:${ELASTIC_PASSWORD} \
  --form file=@/setup/rules.ndjson \
  --cacert /usr/share/elasticsearch/config/certs/ca/ca.crt

echo -e "\n✅ SIEM Rules imported successfully!"

echo "=========================================================="
echo "🚀 SETUP COMPLETE! TLSOC IS READY."
echo "=========================================================="
