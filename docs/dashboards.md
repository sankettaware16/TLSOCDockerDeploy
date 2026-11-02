# Dashboards and monitoring

What the stack monitors, how the **TLSOC - SOC Overview** dashboard gets
installed, and what to do when that step did not finish.

- [What you get](#what-you-get)
- [How it is installed](#how-it-is-installed)
- [`dashboards.sh`](#dashboardssh)
- [Automatic retry](#automatic-retry)
- [The health collector](#the-health-collector)
- [Customising the dashboard](#customising-the-dashboard)
- [Troubleshooting](#troubleshooting)

## What you get

**TLSOC - SOC Overview** is the landing page for the SOC (Kibana → Dashboards):

| Area | Panels |
|---|---|
| Activity | events and average events per second for the selected time range, log volume by source over time, source volume and share, number of active sources |
| Pipeline health | Kafka consumer lag, parser throughput and match rate, Logstash output rate, Elasticsearch heap, storage used, overall SIEM status |
| Components | up / degraded / down for Elasticsearch, Kibana, Logstash, Kafka, the parser engine and the host, with detail |
| Log sources | per-source freshness (active / stale / dead / clock-skew: a source whose newest event is in the *future* has a wrong clock or time zone) |
| Detections | open alerts, alerts by severity over time, top alert rules (from Kibana's Security detection alerts) |
| Threat intelligence | IOCs ingested, IOC types, feeds (from the optional collectors in `intel/`) |

Dropdown controls filter the log panels by **log source**, **source country**
and **domain**. Health, alert and threat-intel panels deliberately always show
the full picture.

It is built to work **from the first minute**, before any log has arrived:
panels that need log data say *No results found* and fill in by themselves as
soon as the engine starts writing. Two tiles show *N/A* until their component
runs: **Parser throughput / match rate** (until the
[TLSOC Engine](https://github.com/sankettaware16/foss-soc-engine) is installed
and running; the Components table says `not-installed` until then, without
turning the overall status red) and **Threat intel IOCs** (until you enable a
feed in `intel/`).

## How it is installed

`install.sh` does it for you, after the stack is up:

1. retention policies and index templates ([details](retention-and-storage.md)),
   including empty base indices so Kibana can resolve every field up front;
2. the health collector and its per-minute cron job (needs root);
3. the Kibana space, if you asked for one;
4. the dashboard and its data views, imported into Kibana;
5. the Security alerts index, so the alert panels have something to read;
6. one extra health reading once Kibana is confirmed up, so the dashboard opens
   on the settled state.

The legacy `kibana/saved_objects/tlsoc_saved_objects.ndjson` is a small example
bundle for older field names; it is **not** imported automatically.

## `dashboards.sh`

One idempotent command that does all of the above. Run it whenever the first
attempt was skipped or failed, after `git pull` (upgrade), or after editing the
dashboard:

```bash
sudo ./dashboards.sh                  # everything, including the health collector
./dashboards.sh --no-collector        # dashboard only; works without root
sudo ./dashboards.sh --space soc      # import into the Kibana space "soc" (created if missing)
sudo ./dashboards.sh --wait 900       # wait up to 15 minutes for Elasticsearch/Kibana
```

| Option | Meaning |
|---|---|
| `--space ID` | Kibana space to import into (default `default`) |
| `--wait SECONDS` | How long to wait for Elasticsearch and Kibana (default 300) |
| `--no-collector` | Skip the health collector and cron job (no root needed). The health panels stay empty until you run it once with `sudo` |
| `--schedule-retry` | If setup fails, retry every 10 minutes (root) |
| `--quiet` | Print errors only |

Without root it still imports the dashboard and tells you to run it with `sudo`
once for the collector. The `ELASTIC_PASSWORD` it uses is read from `.env`.

## Automatic retry

The usual reason the first attempt fails is timing: Kibana needs a minute or two
to start, and a small VM can take longer. When that happens and the installer
is running as root, it installs `/etc/cron.d/tlsoc-dashboards-retry`, which runs
`dashboards.sh` every 10 minutes. The retry job:

- stops and **removes itself** as soon as the setup succeeds;
- gives up (and removes itself) after **24 hours** of failures;
- logs to `/var/log/tlsoc-dashboards.log`.

If the installer was *not* run as root it cannot schedule anything and instead
prints the one command to run (`sudo ./dashboards.sh`). To stop a pending retry
by hand: `sudo rm /etc/cron.d/tlsoc-dashboards-retry`.

## The health collector

`monitoring/tlsoc_health_collector.py` (standard library only) runs every minute
from `/etc/cron.d/tlsoc-health`, as root because it reads container state with
Docker, and writes one document per component to `tlsoc-health-YYYY.MM`
(retained for `HEALTH_RETENTION_DAYS`, default 90):

| Component | What is checked |
|---|---|
| `elasticsearch` | cluster health, heap, disk, documents, indexing rate |
| `kibana` | `/api/status` |
| `logstash` | container state, events in/out rates |
| `kafka` | container state, consumer-group lag |
| `parser-engine` | engine heartbeat, events per second, parse match rate |
| `host` | load, memory, disk |
| `source:<name>` | seconds since the last event per log source |

Things worth knowing:

- **The engine is found automatically** (its systemd service `foss-soc`, or
  `/etc/foss-soc-engine`, `/opt/*`, `~/foss-soc-engine`). Installed somewhere
  else? Run the collector with `--engine-logs /path/to/engine/logs` (edit the cron
  line).
- **The Kafka consumer group is read from the engine's `config.yaml`
  (`kafka.group_id`)**, so lag is reported for the group you actually use. Override
  with `--kafka-group NAME`.
- **No engine installed yet is not an outage:** `parser-engine` shows
  `not-installed` and is left out of the overall status.
- A cluster that is *yellow* shows as degraded. On this single-node stack that
  means an index has replicas that cannot be placed: keep `INDEX_REPLICAS=0`.

Run it by hand to see the readings without indexing anything:

```bash
sudo /usr/local/bin/tlsoc-health-collector --env-file /opt/TLSOCDockerDeploy/.env --dry-run
```

## Customising the dashboard

The dashboard is generated, so changes survive re-imports:

```bash
python3 kibana/generate_overview_dashboard.py            # rewrites tlsoc_overview_dashboard.ndjson
sudo ./dashboards.sh                                      # re-imports it (overwrites in place)
```

Panels have fixed IDs, so importing updates them instead of duplicating. Edits
made only in Kibana's editor are replaced by the next import; to keep them, use
*Save as* to make a copy with a different title.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| No dashboard in Kibana | `sudo ./dashboards.sh`. Check `/var/log/tlsoc-dashboards.log` if a retry is pending |
| `Elasticsearch rejected the password` | `ELASTIC_PASSWORD` in `.env` does not match Elasticsearch (the file was edited or replaced). Restore the original value |
| Health panels empty | The collector is not installed or not running: `sudo ./dashboards.sh`, then `cat /var/log/tlsoc-health.log` |
| Log panels say *No results found* | No events in the selected time range. Widen the range, and check the engine and Logstash (`docker logs logstash`) |
| Panels show an error badge | The data view cannot resolve a field. Run `sudo ./dashboards.sh` (re-creates the base indices and data views); if you changed index names, update `kibana/generate_overview_dashboard.py` |
| *Parser match rate* red / N/A | The engine is not running or has produced nothing yet |
| Log source shows `clock-skew` | That source's clock or time zone is wrong (its newest event is in the future). Fix the source or the engine rule's `tz` |
| Overall `degraded` with cluster yellow | See the collector notes above: replicas on a single node |
