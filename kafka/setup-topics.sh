#!/usr/bin/env bash
# =================================================================
# TLSOC Kafka topics - tune the topics your log sources created
#
#   sudo ./kafka/setup-topics.sh                  # tune existing topics (safe to repeat)
#   sudo ./kafka/setup-topics.sh --install-cron   # ... and re-check every 5 minutes
#   sudo ./kafka/setup-topics.sh --list           # TLSOC topics, partitions, retention
#
# Topics are NOT created in advance. A source's topic, tlsoc.logs.<source>,
# is created by Kafka on that source's first line (KAFKA_DEFAULT_PARTITIONS
# partitions, default 1). This script then gives every EXISTING TLSOC topic
# the settings in kafka/topics.conf: more partitions for busy sources, a
# retention. A source that never sends never gets a topic, so the number of
# topics follows the sources you really have, not the parsers you have.
#
# It never lowers partitions and never touches other topics. It only deletes
# with --remove-unused, and then only TLSOC topics that never held a message.
#
# install.sh runs it with --install-cron for you.
#
# Options:
#   --wait SECONDS     how long to wait for Kafka to answer       (default: 120)
#   --list             only print the TLSOC topics
#   --dry-run          print what would change, change nothing
#   --quiet            print only changes and errors (used by cron)
#   --create NAMES     also create these sources' topics now (comma list),
#                      e.g. to give a busy source its partitions before its
#                      first line
#   --remove-unused    delete TLSOC topics that never held a message (made
#                      in advance by an older version); a source that starts
#                      later gets its topic back automatically
#   --install-cron     install /etc/cron.d/tlsoc-topics (every 5 minutes)
# =================================================================
set -euo pipefail
cd "$(dirname "$0")/.."

CATALOG="${TLSOC_TOPICS_CONF:-kafka/topics.conf}"
CONTAINER="${KAFKA_CONTAINER:-kafka}"
BOOTSTRAP="${KAFKA_BOOTSTRAP:-kafka:9092}"
CRON_FILE="${TLSOC_TOPICS_CRON_FILE:-/etc/cron.d/tlsoc-topics}"
PREFIX="tlsoc.logs."
WAIT=120
MODE=apply
QUIET=0
CREATE=""
REMOVE_UNUSED=0
INSTALL_CRON=0

while [ $# -gt 0 ]; do
  case "$1" in
    --wait) WAIT="$2"; shift 2 ;;
    --list) MODE=list; shift ;;
    --dry-run) MODE=dry-run; shift ;;
    --quiet) QUIET=1; shift ;;
    --create) CREATE="${CREATE:+$CREATE,}$2"; shift 2 ;;
    --remove-unused) REMOVE_UNUSED=1; shift ;;
    --install-cron) INSTALL_CRON=1; shift ;;
    -h|--help) sed -n '2,33p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

say() { [ "$QUIET" = 1 ] || echo "$@"; }
change() { echo "$(date '+%F %T') $*"; }
kt() { docker exec "$CONTAINER" /opt/kafka/bin/kafka-topics.sh --bootstrap-server "$BOOTSTRAP" "$@"; }
kc() { docker exec "$CONTAINER" /opt/kafka/bin/kafka-configs.sh --bootstrap-server "$BOOTSTRAP" "$@"; }

if [ "$INSTALL_CRON" = 1 ] && [ "$MODE" = apply ]; then
  if [ "$(id -u)" != 0 ]; then
    echo "[!] --install-cron needs root: sudo $0 --install-cron" >&2
  else
    cat > "$CRON_FILE" <<EOF
# TLSOC: give new source topics their partitions/retention (kafka/topics.conf)
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
*/5 * * * * root flock -n /run/tlsoc-topics.lock $PWD/kafka/setup-topics.sh --quiet --wait 20 >> /var/log/tlsoc-topics.log 2>&1
EOF
    chmod 0644 "$CRON_FILE"
    say "[+] cron job $CRON_FILE: re-checks topics every 5 minutes (log /var/log/tlsoc-topics.log)"
  fi
fi

# ---- wait for Kafka ----
deadline=$(( $(date +%s) + WAIT ))
until existing="$(kt --list 2>/dev/null)"; do
  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "[!] Kafka did not answer within ${WAIT}s. Start the stack (docker compose up -d) and re-run: sudo ./kafka/setup-topics.sh" >&2
    exit 1
  fi
  sleep 3
done
mine="$(grep "^${PREFIX//./\\.}" <<<"$existing" | sort || true)"

# ---- current state of every TLSOC topic, in one call ----
# "<topic> <partitions> <retention.ms or ->" per line
declare -A CUR_PARTS=() CUR_RET=()
if [ -n "$mine" ]; then
  while read -r topic parts ret; do
    CUR_PARTS[$topic]=$parts; CUR_RET[$topic]=$ret
  done < <(kt --describe --if-exists --topic "${PREFIX//./\\.}.*" 2>/dev/null | awk '
    /PartitionCount/ {
      t = ""; p = ""; r = "-"
      for (i = 1; i <= NF; i++) {
        if ($i == "Topic:") t = $(i + 1)
        if ($i == "PartitionCount:") p = $(i + 1)
        if ($i ~ /retention\.ms=/) { n = split($i, kv, ","); for (j = 1; j <= n; j++) if (kv[j] ~ /^retention\.ms=/) { sub(/^retention\.ms=/, "", kv[j]); r = kv[j] } }
      }
      if (t != "") print t, p, r
    }')
fi

if [ "$MODE" = list ]; then
  printf '%-32s %10s %10s\n' TOPIC PARTITIONS RETENTION
  for t in $mine; do
    r="${CUR_RET[$t]:--}"; [ "$r" != - ] && r="$(( r / 3600000 ))h"
    printf '%-32s %10s %10s\n' "$t" "${CUR_PARTS[$t]:-?}" "$r"
  done
  [ -n "$mine" ] || echo "(none yet: a source's topic appears with its first line)"
  exit 0
fi

# ---- the catalog: settings per source, "*" for every other topic ----
declare -A WANT_PARTS=() WANT_HOURS=()
while read -r name parts hours _; do
  case "$name" in ''|\#*) continue ;; esac
  if ! [[ "$name" =~ ^([a-z0-9][a-z0-9_-]*|\*)$ ]] || ! [[ "$parts" =~ ^[1-9][0-9]*$ ]]; then
    echo "[!] $CATALOG: skipping invalid line: $name $parts" >&2; continue
  fi
  WANT_PARTS[$name]=$parts
  [[ -n "${hours:-}" && "$hours" =~ ^[0-9]+$ ]] && WANT_HOURS[$name]=$hours
done < "$CATALOG"

want_parts() { echo "${WANT_PARTS[$1]:-${WANT_PARTS['*']:-1}}"; }
want_hours() { echo "${WANT_HOURS[$1]:-${WANT_HOURS['*']:-}}"; }

created=0; raised=0; retained=0; removed=0; fine=0

# ---- --create: topics asked for explicitly ----
IFS=',' read -r -a asked <<<"$CREATE"
for name in "${asked[@]}"; do
  [ -n "$name" ] || continue
  if ! [[ "$name" =~ ^[a-z0-9][a-z0-9_-]*$ ]]; then
    echo "[!] --create: invalid source name: $name" >&2; continue
  fi
  topic="${PREFIX}${name}"
  if grep -qx "$topic" <<<"$mine"; then
    say "[*] $topic already exists"; continue
  fi
  parts="$(want_parts "$name")"; hours="$(want_hours "$name")"
  config=(); [ -n "$hours" ] && config=(--config "retention.ms=$(( hours * 3600000 ))")
  change "[+] $topic: create ($parts partition(s)${hours:+, ${hours} h})"
  if [ "$MODE" = apply ]; then
    kt --create --if-not-exists --topic "$topic" --partitions "$parts" "${config[@]}" >/dev/null
  fi
  created=$((created + 1))
done

# ---- --remove-unused: TLSOC topics that never held a message ----
if [ "$REMOVE_UNUSED" = 1 ] && [ -n "$mine" ]; then
  declare -A END=()
  while IFS=: read -r t _ off; do
    END[$t]=$(( ${END[$t]:-0} + off ))
  done < <(docker exec "$CONTAINER" /opt/kafka/bin/kafka-get-offsets.sh --bootstrap-server "$BOOTSTRAP" \
             --topic "${PREFIX//./\\.}.*" 2>/dev/null)
  keep=""
  for t in $mine; do
    if [ -n "${END[$t]+x}" ] && [ "${END[$t]}" = 0 ]; then
      change "[-] $t: delete (never held a message)"
      [ "$MODE" = apply ] && kt --delete --if-exists --topic "$t" >/dev/null
      removed=$((removed + 1))
    else
      keep="$keep $t"
    fi
  done
  mine="$keep"
fi

# ---- tune what exists ----
for topic in $mine; do
  name="${topic#"$PREFIX"}"
  parts="$(want_parts "$name")"; hours="$(want_hours "$name")"
  cur="${CUR_PARTS[$topic]:-}"; ok=1
  if [ -n "$cur" ] && [ "$cur" -lt "$parts" ]; then
    change "[+] $topic: partitions $cur -> $parts"
    [ "$MODE" = apply ] && kt --alter --topic "$topic" --partitions "$parts" >/dev/null
    raised=$((raised + 1)); ok=0
  fi
  if [ -n "$hours" ] && [ "${CUR_RET[$topic]:--}" != "$(( hours * 3600000 ))" ]; then
    change "[+] $topic: retention -> ${hours} h"
    if [ "$MODE" = apply ]; then
      kc --alter --entity-type topics --entity-name "$topic" \
        --add-config "retention.ms=$(( hours * 3600000 ))" >/dev/null
    fi
    retained=$((retained + 1)); ok=0
  fi
  [ "$ok" = 1 ] && fine=$((fine + 1))
done

word=""; [ "$MODE" = dry-run ] && word=" (dry run, nothing changed)"
total=$(( created + raised + retained + removed ))
if [ "$QUIET" = 0 ] || [ "$total" -gt 0 ]; then
  echo "[+] TLSOC topics: $fine fine, $raised more partitions, $retained retention set, $created created, $removed removed$word"
fi
if [ "$QUIET" = 0 ] && [ -z "${mine// /}" ] && [ "$created" = 0 ]; then
  echo "    No source has sent a line yet; each source's topic appears with its first line."
fi
