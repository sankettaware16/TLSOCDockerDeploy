#!/usr/bin/env bash
# =================================================================
# TLSOC dashboards + monitoring - install, repair or upgrade
#
#   sudo ./dashboards.sh              # full setup (recommended)
#   ./dashboards.sh --no-collector    # dashboards only, no root needed
#
# Safe to run any number of times. It makes sure everything the
# "TLSOC - SOC Overview" dashboard needs is in place:
#
#   1. Elasticsearch is reachable
#   2. retention policies + index templates (elasticsearch/setup_storage.py)
#   3. the health collector + its per-minute cron job        (needs root)
#   4. the Kibana space (if --space is not "default")
#   5. the SOC Overview dashboard + data views imported into Kibana
#   6. the Security alerts index, so the alert panels have data to read
#
# install.sh runs this for you. Run it yourself when the first attempt was
# skipped or failed (for example Kibana was still starting, or install.sh was
# not run as root), after upgrading this repository, or after editing the
# dashboard.
#
# Options:
#   --space ID        Kibana space to import into              (default: default)
#   --wait SECONDS    how long to wait for Elasticsearch/Kibana (default: 300)
#   --no-collector    skip the health collector + cron (works without root)
#   --schedule-retry  if setup fails, retry every 10 minutes (needs root)
#   --from-install    called by install.sh: implies --schedule-retry
#   --from-cron       called by the retry job; gives up after 24 hours
#   --quiet           print errors only
#   -h, --help        show this help
# =================================================================
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="${ENV_FILE:-$HERE/.env}"
SPACE="default"
WAIT=300
COLLECTOR=yes
SCHEDULE=no
FROM_CRON=no
QUIET=no

CRON_FILE="${TLSOC_CRON_FILE:-/etc/cron.d/tlsoc-dashboards-retry}"
STATE_DIR="${TLSOC_STATE_DIR:-/var/lib/tlsoc}"
ATTEMPTS_FILE="$STATE_DIR/dashboards-attempts"
MAX_ATTEMPTS=144                      # 144 x 10 minutes = 24 hours
LOG_FILE="${TLSOC_LOG_FILE:-/var/log/tlsoc-dashboards.log}"

usage() { sed -n '2,/^# =====*$/p' "$0" | sed 's/^# \{0,1\}//' | sed '$d'; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --space)          SPACE="${2:?--space needs an id}"; shift 2 ;;
    --wait)           WAIT="${2:?--wait needs seconds}"; shift 2 ;;
    --no-collector)   COLLECTOR=no; shift ;;
    --schedule-retry) SCHEDULE=yes; shift ;;
    --from-install)   SCHEDULE=yes; shift ;;
    --from-cron)      FROM_CRON=yes; QUIET=yes; shift ;;
    --quiet)          QUIET=yes; shift ;;
    -h|--help)        usage; exit 0 ;;
    *) echo "unknown option: $1 (try --help)" >&2; exit 2 ;;
  esac
done

say() { [[ "$QUIET" == yes ]] || echo "$@"; }
log() { echo "$(date -Is) $*" >> "$LOG_FILE" 2>/dev/null || true; }

IS_ROOT=no; [[ $EUID -eq 0 ]] && IS_ROOT=yes
if [[ "$COLLECTOR" == yes && "$IS_ROOT" == no ]]; then
  say "[dashboards] not running as root: importing dashboards only."
  say "             For the health collector (fills the health panels) also run: sudo ./dashboards.sh"
  COLLECTOR=no
fi

[[ -f "$ENV_FILE" ]] || { echo "[dashboards] .env not found at $ENV_FILE - run ./install.sh first" >&2; exit 2; }

# ---- retry job bookkeeping ----------------------------------------------
remove_retry() {
  rm -f "$CRON_FILE" "$ATTEMPTS_FILE" 2>/dev/null || true
}
schedule_retry() {
  if [[ "$IS_ROOT" != yes ]]; then
    echo "[dashboards] not root, so no automatic retry was scheduled."
    echo "             Run again when Elasticsearch and Kibana are up:  sudo ./dashboards.sh"
    return
  fi
  mkdir -p "$STATE_DIR" "$(dirname "$CRON_FILE")"
  cat > "$CRON_FILE" <<CRON
# TLSOC: retry the dashboard setup until it succeeds (removed automatically).
*/10 * * * * root cd $HERE && ENV_FILE=$ENV_FILE ./dashboards.sh --from-cron --space $SPACE --wait 120 >> $LOG_FILE 2>&1
CRON
  chmod 0644 "$CRON_FILE"
  echo "[dashboards] setup incomplete - will retry automatically every 10 minutes (log: $LOG_FILE)."
  echo "             Or run it yourself any time:  sudo ./dashboards.sh"
}

if [[ "$FROM_CRON" == yes ]]; then
  mkdir -p "$STATE_DIR" 2>/dev/null || true
  n=$(( $(cat "$ATTEMPTS_FILE" 2>/dev/null || echo 0) + 1 ))
  echo "$n" > "$ATTEMPTS_FILE" 2>/dev/null || true
  if (( n > MAX_ATTEMPTS )); then
    log "giving up after $MAX_ATTEMPTS attempts; run ./dashboards.sh by hand and check the log"
    remove_retry
    exit 1
  fi
  log "retry attempt $n"
fi

# ---- the work -------------------------------------------------------------
rc=0
say "[dashboards] 1/2 retention policies + index templates"
if command -v python3 >/dev/null; then
  ES_ARGS=()
  [[ -n "${ES_URL:-}" ]] && ES_ARGS=(--es-url "$ES_URL")
  python3 "$HERE/elasticsearch/setup_storage.py" --env-file "$ENV_FILE" "${ES_ARGS[@]}" \
    | { [[ "$QUIET" == yes ]] && cat >/dev/null || cat; } || rc=1
  [[ ${PIPESTATUS[0]} -eq 0 ]] || rc=1
else
  echo "[dashboards] python3 is required" >&2; rc=1
fi

if [[ $rc -eq 0 ]]; then
  say "[dashboards] 2/2 health collector + dashboard"
  SKIP_COLLECTOR=""; [[ "$COLLECTOR" == no ]] && SKIP_COLLECTOR=1
  ENV_FILE="$ENV_FILE" KIBANA_SPACE="$SPACE" WAIT_SECONDS="$WAIT" SKIP_COLLECTOR="$SKIP_COLLECTOR" \
    "$HERE/monitoring/setup-monitoring.sh" \
    | { [[ "$QUIET" == yes ]] && cat >/dev/null || cat; }
  [[ ${PIPESTATUS[0]} -eq 0 ]] || rc=1
fi

if [[ $rc -eq 0 ]]; then
  remove_retry
  log "dashboards setup complete"
  say "[dashboards] done."
  exit 0
fi

log "dashboards setup incomplete"
[[ "$SCHEDULE" == yes && "$FROM_CRON" == no ]] && schedule_retry
[[ "$FROM_CRON" == yes ]] || echo "[dashboards] setup did not complete - see messages above." >&2
exit 1
