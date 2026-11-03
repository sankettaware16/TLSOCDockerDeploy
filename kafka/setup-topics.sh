#!/usr/bin/env bash
# =================================================================
# TLSOC Kafka topics - create or upgrade the standard topics
#
#   sudo ./kafka/setup-topics.sh            # create / upgrade (safe to repeat)
#   sudo ./kafka/setup-topics.sh --list     # show TLSOC topics and partitions
#
# Every log source has its own topic, tlsoc.logs.<source> (see
# kafka/topics.conf). This script creates the listed topics with the
# partition count and retention given there, and raises the partition count
# of an existing topic if topics.conf asks for more. It never deletes a
# topic, never lowers partitions and never touches other topics.
#
# Sources that are not listed still work: their topic is created on first
# use with KAFKA_DEFAULT_PARTITIONS partitions (.env).
#
# install.sh runs this for you.
#
# Options:
#   --wait SECONDS   how long to wait for Kafka to answer   (default: 120)
#   --list           only print the TLSOC topics
#   --dry-run        print what would change, change nothing
# =================================================================
set -euo pipefail
cd "$(dirname "$0")/.."

CATALOG="kafka/topics.conf"
CONTAINER="${KAFKA_CONTAINER:-kafka}"
BOOTSTRAP="${KAFKA_BOOTSTRAP:-kafka:9092}"
PREFIX="tlsoc.logs."
WAIT=120
MODE=apply

while [ $# -gt 0 ]; do
  case "$1" in
    --wait) WAIT="$2"; shift 2 ;;
    --list) MODE=list; shift ;;
    --dry-run) MODE=dry-run; shift ;;
    -h|--help) sed -n '2,23p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

kt() { docker exec "$CONTAINER" /opt/kafka/bin/kafka-topics.sh --bootstrap-server "$BOOTSTRAP" "$@"; }
kc() { docker exec "$CONTAINER" /opt/kafka/bin/kafka-configs.sh --bootstrap-server "$BOOTSTRAP" "$@"; }

# ---- wait for Kafka ----
deadline=$(( $(date +%s) + WAIT ))
until existing="$(kt --list 2>/dev/null)"; do
  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "[!] Kafka did not answer within ${WAIT}s. Start the stack (docker compose up -d) and re-run: sudo ./kafka/setup-topics.sh" >&2
    exit 1
  fi
  sleep 3
done

partitions_of() {
  kt --describe --topic "$1" 2>/dev/null | sed -n 's/.*PartitionCount: *\([0-9]*\).*/\1/p' | head -1
}

if [ "$MODE" = list ]; then
  printf '%-32s %s\n' TOPIC PARTITIONS
  grep "^${PREFIX//./\\.}" <<<"$existing" | sort | while read -r t; do
    printf '%-32s %s\n' "$t" "$(partitions_of "$t")"
  done
  exit 0
fi

created=0; raised=0; unchanged=0
while read -r name parts hours _; do
  case "$name" in ''|\#*) continue ;; esac
  if ! [[ "$name" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || ! [[ "$parts" =~ ^[1-9][0-9]*$ ]]; then
    echo "[!] $CATALOG: skipping invalid line: $name $parts" >&2; continue
  fi
  topic="${PREFIX}${name}"
  config=()
  if [[ -n "${hours:-}" && "$hours" =~ ^[0-9]+$ ]]; then
    config=(--config "retention.ms=$(( hours * 3600000 ))")
  fi
  if grep -qx "$topic" <<<"$existing"; then
    cur="$(partitions_of "$topic")"
    if [ -n "$cur" ] && [ "$cur" -lt "$parts" ]; then
      echo "[+] $topic: partitions $cur -> $parts"
      [ "$MODE" = apply ] && kt --alter --topic "$topic" --partitions "$parts" >/dev/null
      raised=$((raised + 1))
    else
      if [ -n "$cur" ] && [ "$cur" -gt "$parts" ]; then
        echo "[*] $topic: keeps $cur partitions (Kafka cannot lower it to $parts)"
      fi
      unchanged=$((unchanged + 1))
    fi
    if [ ${#config[@]} -gt 0 ] && [ "$MODE" = apply ]; then
      kc --alter --entity-type topics --entity-name "$topic" \
        --add-config "retention.ms=$(( hours * 3600000 ))" >/dev/null
    fi
  else
    echo "[+] $topic: create ($parts partition(s))"
    [ "$MODE" = apply ] && kt --create --if-not-exists --topic "$topic" --partitions "$parts" "${config[@]}" >/dev/null
    created=$((created + 1))
  fi
done < "$CATALOG"

word=""; [ "$MODE" = dry-run ] && word=" (dry run, nothing changed)"
echo "[+] Kafka topics: $created created, $raised upgraded, $unchanged already fine$word"
