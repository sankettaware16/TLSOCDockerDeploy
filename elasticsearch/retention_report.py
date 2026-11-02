#!/usr/bin/env python3
"""
TLSOC retention report - does your retention fit your disk?
============================================================
Measures how much storage each log source really uses per day, projects that
to the retention configured in .env, and compares it with the disk Elasticsearch
has. Run it after the stack has been collecting for a few days, and again
whenever you add a log source or change retention.

    ./elasticsearch/retention_report.py            # uses .env + 3 full days
    ./elasticsearch/retention_report.py --days 7   # average over 7 full days

Exit status: 0 = fits, 1 = does not fit (or the data needed is missing).
Standard library only.
"""

import argparse
import collections
import datetime
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import setup_storage as ss  # noqa: E402  (shared config + client)

GB = 1024 ** 3
# Keep the disk under this share of its capacity: Elasticsearch stops writing
# at the 95% flood-stage watermark, and needs room to merge segments.
TARGET_DISK_SHARE = 0.70


def fmt_gb(b):
    return f"{b / GB:,.1f} GB"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--env-file", default=os.environ.get(
        "ENV_FILE", os.path.join(ss.REPO, ".env")))
    ap.add_argument("--es-url", default=os.environ.get("ES_URL"))
    ap.add_argument("--ca-cert", default=os.path.join(ss.REPO, "certs", "ca", "ca.crt"))
    ap.add_argument("--days", type=int, default=3,
                    help="number of most recent FULL days to average (default 3)")
    args = ap.parse_args()

    cfg = ss.load_config(args)
    url = args.es_url or f"https://{cfg['host_ip'] or 'localhost'}:9200"
    es = ss.ES(url, "elastic", cfg["password"], args.ca_cert, False)

    rows = es.get("/_cat/indices/fosstlsoc-logs-*?format=json&bytes=b&h=index,store.size,docs.count")
    per_source = collections.defaultdict(dict)   # source -> {day: bytes}
    for r in rows if isinstance(rows, list) else []:
        m = re.fullmatch(r"fosstlsoc-logs-(.+)-(\d{4}\.\d{2}\.\d{2})", r["index"])
        if m:
            per_source[m.group(1)][m.group(2)] = int(r["store.size"] or 0)
    if not per_source:
        print("No fosstlsoc-logs-* indices yet - let the stack collect for a few days, then re-run.")
        return 1

    # Indices are named by event day (UTC); today's is still filling up.
    today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y.%m.%d")
    all_days = sorted({d for days in per_source.values() for d in days if d != today})
    window = all_days[-args.days:]
    if not window:
        print(f"Only today ({today}) has data - re-run tomorrow for a meaningful average.")
        return 1

    alloc = es.get("/_cat/allocation?format=json&bytes=b")
    node = next((a for a in alloc if a.get("disk.total")), None) if isinstance(alloc, list) else None
    if not node:
        print("Could not read disk usage from Elasticsearch.")
        return 1
    disk_total, disk_avail = int(node["disk.total"]), int(node["disk.avail"])
    disk_used_other = int(node["disk.used"]) - int(node["disk.indices"] or 0)
    current_logs = sum(sum(days.values()) for days in per_source.values())

    print(f"Average over {len(window)} full day(s): {window[0]} .. {window[-1]}\n")
    print(f"{'source':<22}{'GB/day':>10}{'keep (d)':>10}{'projected':>14}")
    total_projected = total_daily = 0.0
    daily = {}
    for src, days in sorted(per_source.items(), key=lambda kv: -sum(kv[1].get(d, 0) for d in window)):
        avg = sum(days.get(d, 0) for d in window) / len(window)
        keep = cfg["hv_retention"] if src in cfg["hv_sources"] else cfg["retention"]
        daily[src] = avg
        total_daily += avg
        total_projected += avg * keep
        flag = "  (high-volume tier)" if src in cfg["hv_sources"] else ""
        print(f"{src:<22}{avg / GB:>10,.1f}{keep:>10}{fmt_gb(avg * keep):>14}{flag}")
    print(f"{'TOTAL':<22}{total_daily / GB:>10,.1f}{'':>10}{fmt_gb(total_projected):>14}")

    # Health/threat-intel data is small next to logs; keep a flat allowance.
    budget = disk_total * TARGET_DISK_SHARE - disk_used_other
    print(f"\nDisk: {fmt_gb(disk_total)} total, {fmt_gb(disk_avail)} free; "
          f"{fmt_gb(disk_used_other)} used by things other than indices")
    print(f"Budget for log indices at {int(TARGET_DISK_SHARE * 100)}% of the disk: {fmt_gb(budget)}")
    print(f"Currently stored: {fmt_gb(current_logs)}; projected at full retention: "
          f"{fmt_gb(total_projected)}")
    print("(Warm-phase compaction typically shrinks older data further; "
          "treat the projection as an upper bound.)")

    if total_projected <= budget:
        print("\nOK: the configured retention fits on this disk.")
        return 0

    print("\nNOT OK: the configured retention will not fit.")
    if total_daily > 0:
        print(f"  At today's volume the whole disk budget holds about "
              f"{int(budget / total_daily)} days of ALL sources.")
    print("  Options, cheapest first:")
    # Greedy suggestion: move the heaviest sources to the high-volume tier.
    suggested, projected = [], total_projected
    for src, avg in sorted(daily.items(), key=lambda kv: -kv[1]):
        if projected <= budget:
            break
        if src in cfg["hv_sources"]:
            continue
        projected -= avg * (cfg["retention"] - cfg["hv_retention"])
        suggested.append(src)
    if suggested and projected <= budget:
        print(f"   1. Put the heaviest sources on the shorter tier: in .env set\n"
              f"        HIGH_VOLUME_SOURCES={','.join(sorted(set(cfg['hv_sources'] + suggested)))}\n"
              f"        HIGH_VOLUME_RETENTION_DAYS={cfg['hv_retention']}\n"
              f"      then run ./elasticsearch/setup_storage.py  (projected {fmt_gb(projected)})")
    else:
        print("   1. Move the heaviest sources to the high-volume tier "
              "(HIGH_VOLUME_SOURCES / HIGH_VOLUME_RETENTION_DAYS) - even then it "
              "will not fit, so also consider 2 and 3.")
    print("   2. Add disk (or a bigger volume for Docker's data root).")
    print("   3. Reduce volume at the source: engine `output.include_original: false` "
          "roughly halves index size, and noisy sources can be filtered upstream.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
