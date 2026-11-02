"""Shared helpers for the TLSOC threat-intelligence collectors.

Every collector fetches indicators of compromise (IOCs) from one feed and
appends them as NDJSON to <engine output>/threat_intel/<feed>.json, where the
`threat_intel` Logstash pipeline picks them up (see logstash/pipeline/).

Configuration is environment-only (see intel/.env.example):

  TLSOC_OUTPUT_DIR    engine output folder (default: ENGINE_OUTPUT_DIR from the
                      stack .env, else /var/log/soc_output)
  TLSOC_INTEL_CACHE   where "already seen" state is kept (default: intel/cache)
"""

import json
import os
import sys
import tempfile
from datetime import datetime, timezone

import requests

HERE = os.path.dirname(os.path.abspath(__file__))

OUTPUT_DIR = os.path.join(
    os.environ.get("TLSOC_OUTPUT_DIR")
    or os.environ.get("ENGINE_OUTPUT_DIR")
    or "/var/log/soc_output",
    "threat_intel",
)
CACHE_DIR = os.environ.get("TLSOC_INTEL_CACHE") or os.path.join(HERE, "cache")

HTTP_TIMEOUT = 60


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def require_env(name):
    """Return a required environment variable or exit with a clear message."""
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"[!] {name} is not set - add it to intel/.env", file=sys.stderr)
        sys.exit(1)
    return value


def http_get(url, **kwargs):
    """GET with a timeout; raises on HTTP errors so cron/systemd can alert."""
    response = requests.get(url, timeout=HTTP_TIMEOUT, **kwargs)
    response.raise_for_status()
    return response


def load_seen(feed):
    """Set of IOC values already written for this feed (empty on first run)."""
    path = os.path.join(CACHE_DIR, f"{feed}_seen.json")
    try:
        with open(path) as f:
            return set(json.load(f))
    except (OSError, ValueError):
        return set()


def save_seen(feed, seen):
    """Persist the seen-set atomically so an interrupted run cannot corrupt it."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=CACHE_DIR)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(sorted(seen), f)
        os.replace(tmp, os.path.join(CACHE_DIR, f"{feed}_seen.json"))
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def write_events(feed, events):
    """Append events to <OUTPUT_DIR>/<feed>.json (one JSON object per line)."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(os.path.join(OUTPUT_DIR, f"{feed}.json"), "a") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")


def ioc_event(feed, ioc_type, value, **extra):
    """Build one IOC document in the shape the threat_intel pipeline expects."""
    return {
        "tlsoc_type": "threat_intel",
        "intel_source": feed,
        "ioc_type": ioc_type,
        "ioc_value": value,
        **extra,
        "@timestamp": now_iso(),
    }
