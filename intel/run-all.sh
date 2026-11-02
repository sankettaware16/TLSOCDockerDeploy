#!/usr/bin/env bash
# Run every threat-intel collector that is configured. Safe to call from cron.
#
#   0 * * * * /opt/TLSOCDockerDeploy/intel/run-all.sh >> /var/log/tlsoc-intel.log 2>&1
#
# Loads intel/.env, skips feeds whose key is empty, and exits non-zero if any
# collector that did run failed.
set -uo pipefail
cd "$(dirname "$0")"

if [ -f .env ]; then
  set -a; . ./.env; set +a
fi

PY="${PYTHON:-python3}"
[ -x .venv/bin/python ] && PY=".venv/bin/python"

rc=0
run() { echo "[$(date -Is)] $1"; "$PY" "$1" || { echo "[!] $1 failed"; rc=1; }; }

[ -n "${ABUSEIPDB_API_KEY:-}" ]               && run abuseipdb_collector.py
[ -n "${OTX_API_KEY:-}" ]                     && run otx_collector.py
[ -n "${MISP_URL:-}" ] && [ -n "${MISP_KEY:-}" ] && run misp_collector.py
run openphish_collector.py   # public feed, no key

exit $rc
