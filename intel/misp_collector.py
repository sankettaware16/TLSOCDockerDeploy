#!/usr/bin/env python3
"""MISP -> TLSOC threat-intel collector.

Pulls IOCs from a MISP instance incrementally and appends them as NDJSON for
the `threat_intel` Logstash pipeline.

  * Paginates, so it sees every attribute, not just the first page.
  * Fetches incrementally using MISP's `timestamp` filter: each run only asks
    for what changed since the last successful run.
  * Bounded cache (only recent UUIDs are kept) and atomic state writes, so a
    crash mid-run cannot corrupt the state file.
  * Exits non-zero on failure so cron/systemd can alert.

Environment (see intel/.env.example):
  MISP_URL            required, e.g. https://misp.example.org
  MISP_KEY            required, a MISP auth key
  MISP_VERIFY_SSL     "true" (default) or "false" for a self-signed instance
  MISP_TO_IDS_ONLY    "true" to collect only attributes flagged to_ids
"""

import json
import os
import sys
import tempfile
import logging
from datetime import datetime, timezone

import urllib3
from pymisp import PyMISP

import common

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ----------------------------------------------------------------------
# Config  (override via environment)
# ----------------------------------------------------------------------
MISP_URL = os.environ.get("MISP_URL", "")
MISP_KEY = os.environ.get("MISP_KEY", "")
VERIFY_SSL = os.environ.get("MISP_VERIFY_SSL", "true").lower() == "true"

OUTPUT_FILE = os.environ.get(
    "MISP_OUTPUT", os.path.join(common.OUTPUT_DIR, "misp.json")
)
STATE_FILE = os.environ.get(
    "MISP_STATE", os.path.join(common.CACHE_DIR, "misp_state.json")
)

# Attribute types to collect. Add "url", "md5", "sha256" etc. as needed.
IOC_TYPES = ["ip-dst", "ip-src", "domain", "hostname", "url"]

PAGE_SIZE = 1000            # attributes per API request
MAX_PAGES = 500             # safety stop: 500 * 1000 = 500k per type per run
CACHE_MAX = 200_000         # UUIDs retained for dedup
FIRST_RUN_LOOKBACK = "30d"  # how far back to reach on a cold start
TO_IDS_ONLY = os.environ.get("MISP_TO_IDS_ONLY", "false").lower() == "true"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("misp_collector")


# ----------------------------------------------------------------------
# State handling
# ----------------------------------------------------------------------
def load_state():
    """Return (last_run_epoch, seen_uuids). Missing/corrupt state = cold start."""
    if not os.path.exists(STATE_FILE):
        return None, set()
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
        return data.get("last_run"), set(data.get("seen", []))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("State file unreadable (%s) - treating as cold start", exc)
        return None, set()


def save_state(last_run, seen):
    """Write state atomically so an interrupted run can't corrupt it."""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)

    # Keep only the most recent UUIDs so the file stays a sane size.
    trimmed = list(seen)[-CACHE_MAX:]

    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(STATE_FILE))
    try:
        with os.fdopen(fd, "w") as f:
            json.dump({"last_run": last_run, "seen": trimmed}, f)
        os.replace(tmp, STATE_FILE)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


# ----------------------------------------------------------------------
# Fetch
# ----------------------------------------------------------------------
def fetch_attributes(misp, ioc_type, since):
    """Yield attributes of one type, paging until MISP stops returning rows."""
    for page in range(1, MAX_PAGES + 1):
        kwargs = {
            "controller": "attributes",
            "type_attribute": ioc_type,
            "limit": PAGE_SIZE,
            "page": page,
            "timestamp": since,
        }
        if TO_IDS_ONLY:
            kwargs["to_ids"] = True

        result = misp.search(**kwargs)

        if isinstance(result, dict) and "errors" in result:
            raise RuntimeError(f"MISP API error: {result['errors']}")

        batch = result.get("Attribute", []) if isinstance(result, dict) else []
        if not batch:
            return

        log.info("  %s page %d: %d attributes", ioc_type, page, len(batch))
        yield from batch

        if len(batch) < PAGE_SIZE:
            return  # last page

    log.warning("Hit MAX_PAGES for %s - some data may be unread", ioc_type)


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    if not MISP_URL or not MISP_KEY:
        log.error("MISP_URL and MISP_KEY must be set (see intel/.env.example).")
        return 1

    last_run, seen = load_state()
    since = FIRST_RUN_LOOKBACK if last_run is None else str(last_run)
    log.info("Fetching attributes changed since: %s", since)

    try:
        misp = PyMISP(MISP_URL, MISP_KEY, VERIFY_SSL)
    except Exception as exc:
        log.error("Cannot connect to MISP at %s: %s", MISP_URL, exc)
        return 1

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

    # Timestamp the run *before* fetching, so anything written mid-run is
    # picked up next time rather than silently skipped.
    run_started = int(datetime.now(timezone.utc).timestamp())

    total_new = 0
    total_skipped = 0

    try:
        with open(OUTPUT_FILE, "a") as out:
            for ioc_type in IOC_TYPES:
                log.info("Collecting %s ...", ioc_type)
                for attribute in fetch_attributes(misp, ioc_type, since):
                    uuid = attribute.get("uuid")
                    value = attribute.get("value")
                    if not value or not uuid:
                        continue
                    if uuid in seen:
                        total_skipped += 1
                        continue

                    event = {
                        "tlsoc_type": "threat_intel",
                        "intel_source": "misp",
                        "ioc_type": attribute.get("type"),
                        "ioc_value": value,
                        "uuid": uuid,
                        "event_id": attribute.get("event_id"),
                        "category": attribute.get("category"),
                        "to_ids": attribute.get("to_ids"),
                        "comment": attribute.get("comment"),
                        "misp_timestamp": attribute.get("timestamp"),
                        "@timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    out.write(json.dumps(event) + "\n")
                    seen.add(uuid)
                    total_new += 1

    except Exception as exc:
        log.error("Collection failed: %s", exc)
        # Deliberately do NOT advance last_run, so the next run retries this window.
        save_state(last_run, seen)
        return 1

    save_state(run_started, seen)
    log.info("New IOCs: %d | Duplicates skipped: %d", total_new, total_skipped)
    return 0


if __name__ == "__main__":
    sys.exit(main())

