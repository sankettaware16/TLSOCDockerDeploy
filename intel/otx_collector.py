#!/usr/bin/env python3
"""AlienVault OTX subscribed pulses -> TLSOC threat-intel collector.

Needs OTX_API_KEY (free key: https://otx.alienvault.com/settings).
"""

import common

FEED = "otx"
URL = "https://otx.alienvault.com/api/v1/pulses/subscribed"


def main():
    key = common.require_env("OTX_API_KEY")
    response = common.http_get(URL, headers={"X-OTX-API-KEY": key})

    seen = common.load_seen(FEED)
    events, skipped = [], 0
    for pulse in response.json().get("results", []):
        for ioc in pulse.get("indicators", []):
            value = ioc.get("indicator")
            if not value:
                continue
            if value in seen:
                skipped += 1
                continue
            events.append(common.ioc_event(
                FEED, ioc.get("type"), value, pulse_name=pulse.get("name")))
            seen.add(value)

    common.write_events(FEED, events)
    common.save_seen(FEED, seen)
    print(f"[+] New OTX IOCs added: {len(events)}")
    print(f"[+] Duplicates skipped: {skipped}")


if __name__ == "__main__":
    main()
