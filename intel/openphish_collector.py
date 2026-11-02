#!/usr/bin/env python3
"""OpenPhish community feed -> TLSOC threat-intel collector (no key needed)."""

import common

FEED = "openphish"
URL = "https://openphish.com/feed.txt"


def main():
    response = common.http_get(URL)

    seen = common.load_seen(FEED)
    events, skipped = [], 0
    for url in response.text.splitlines():
        url = url.strip()
        if not url:
            continue
        if url in seen:
            skipped += 1
            continue
        events.append(common.ioc_event(FEED, "url", url))
        seen.add(url)

    common.write_events(FEED, events)
    common.save_seen(FEED, seen)
    print(f"[+] New OpenPhish URLs added: {len(events)}")
    print(f"[+] Duplicates skipped: {skipped}")


if __name__ == "__main__":
    main()
