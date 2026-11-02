#!/usr/bin/env python3
"""AbuseIPDB blacklist -> TLSOC threat-intel collector.

Needs ABUSEIPDB_API_KEY (free key: https://www.abuseipdb.com/account/api).
Optional: ABUSEIPDB_MIN_CONFIDENCE (default 90).
"""

import os

import common

FEED = "abuseipdb"
URL = "https://api.abuseipdb.com/api/v2/blacklist"


def main():
    key = common.require_env("ABUSEIPDB_API_KEY")
    confidence = os.environ.get("ABUSEIPDB_MIN_CONFIDENCE", "90")

    response = common.http_get(
        URL,
        headers={"Key": key, "Accept": "application/json"},
        params={"confidenceMinimum": confidence},
    )

    seen = common.load_seen(FEED)
    events, skipped = [], 0
    for item in response.json().get("data", []):
        value = item["ipAddress"]
        if value in seen:
            skipped += 1
            continue
        events.append(common.ioc_event(
            FEED, "ip", value, abuse_score=item.get("abuseConfidenceScore")))
        seen.add(value)

    common.write_events(FEED, events)
    common.save_seen(FEED, seen)
    print(f"[+] New AbuseIPDB IOCs added: {len(events)}")
    print(f"[+] Duplicates skipped: {skipped}")


if __name__ == "__main__":
    main()
