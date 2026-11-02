# Data retention and storage

How long TLSOC keeps your logs, why the default is what it is, how to change it,
and how to keep the disk healthy. Everything here is driven by a handful of
values in `.env`; there is nothing to edit inside Elasticsearch by hand.

- [The default policy](#the-default-policy)
- [Why 180 days](#why-180-days)
- [Settings](#settings)
- [Change the retention](#change-the-retention)
- [Will it fit on my disk?](#will-it-fit-on-my-disk)
- [Keep storage healthy](#keep-storage-healthy)
- [Edit field mappings and index settings](#edit-field-mappings-and-index-settings)
- [What gets created](#what-gets-created)
- [When the disk fills up](#when-the-disk-fills-up)
- [Adopting an existing installation](#adopting-an-existing-installation)

## The default policy

Parsed logs are stored in one index per source per day
(`fosstlsoc-logs-<source>-YYYY.MM.dd`). Each index follows this lifecycle,
managed by Elasticsearch ILM (index lifecycle management):

```
day 0                 day 7                                 day 180
  │  HOT                │  WARM                               │  DELETE
  │  being written,     │  compacted: merged to one segment,  │  index removed
  │  searched often     │  stronger compression, lower        │
  │                     │  priority. Still fully searchable.  │
```

| Data | Index | Default retention |
|---|---|---|
| Parsed logs (all sources) | `fosstlsoc-logs-*` | **180 days** (compacted after 7) |
| Chatty sources you choose (optional) | `fosstlsoc-logs-<source>-*` | 30 days (`HIGH_VOLUME_*`) |
| Self-monitoring (health collector) | `tlsoc-health-*` | 90 days |
| Threat-intelligence IOCs | `tlsoc-threat-intel` | not time-based (see [below](#threat-intelligence-data)) |

Older TLSOC versions did not manage retention at all. If you ran a custom
short policy of your own (for example 5 days to survive a small disk), nothing
is overridden: see [Adopting an existing installation](#adopting-an-existing-installation).

## Why 180 days

The default follows the **CERT-In Directions of 28 April 2022** (No.
20(3)/2022-CERT-In, issued under section 70B(6) of the Information Technology
Act, 2000). Among other things, they require service providers, intermediaries,
data centres, body corporates and Government organisations to **enable logs of
all their ICT systems and maintain them securely for a rolling period of 180
days**, and to provide them to CERT-In when an incident is reported or when
directed. CERT-In's published FAQs say the logs may be held outside India as long
as they are made available to CERT-In on request.

What that means for TLSOC:

- **Keep at least 180 days** of the logs of your systems. `LOG_RETENTION_DAYS=180`
  is the shipped default for that reason.
- **"Securely"** means more than the retention number: restrict who can read and
  delete the data (Kibana roles), keep the stack's disk encrypted and backed up
  if your policy requires it, and keep accurate time on every source (the
  engine records the event's own timestamp, and flags sources with wrong clocks).
  Deleting indices at day 180 is not a backup: see [Backups](#backups).
- **Report within the required time.** Retention is one of several obligations
  in the Directions (incident reporting, time synchronisation, and others). TLSOC
  helps with the logs; it does not make an organisation compliant by itself.

Other rules you may also be subject to, for comparison: PCI DSS v4.0 requires at
least 12 months of audit-log history with 3 months immediately available;
sector regulators (for example RBI for banks) set their own periods. And logs
contain personal data (IP addresses, user names), so under India's Digital
Personal Data Protection Act, 2023 you should not keep them longer than your
legal and security purposes require. **Confirm the period that applies to you
with your compliance officer and the current text on
[cert-in.org.in](https://www.cert-in.org.in); this guide is not legal advice.**

## Settings

All in `.env` (template: `.env.example`):

| Variable | Default | Meaning |
|---|---|---|
| `LOG_RETENTION_DAYS` | `180` | Days to keep parsed logs |
| `WARM_AFTER_DAYS` | `7` | Compact an index after this many days (must be below the retention) |
| `HIGH_VOLUME_SOURCES` | *(empty)* | Comma-separated sources kept for less time, e.g. `squid,dns`. The name is the index name part: `fosstlsoc-logs-<source>-…` |
| `HIGH_VOLUME_RETENTION_DAYS` | `30` | Days to keep those sources |
| `HEALTH_RETENTION_DAYS` | `90` | Days to keep `tlsoc-health-*` |
| `INDEX_SHARDS` | `1` | Primary shards per daily index. Raise only if one source exceeds ~50 GB per day |
| `INDEX_REPLICAS` | `0` | Replicas. Keep `0`: this stack runs one Elasticsearch node, so a replica can never be placed and the cluster would stay *yellow* |

## Change the retention

1. Edit the values in `.env`.
2. Preview, then apply:

   ```bash
   ./elasticsearch/setup_storage.py --dry-run      # shows what would change
   ./elasticsearch/setup_storage.py                # applies it
   ```

   (`sudo ./dashboards.sh` runs the same step as part of its repair/upgrade
   run.)

How a change takes effect:

| You change | Applies to |
|---|---|
| `LOG_RETENTION_DAYS`, `WARM_AFTER_DAYS`, `HIGH_VOLUME_RETENTION_DAYS`, `HEALTH_RETENTION_DAYS` | **All** indices already on that policy, at Elasticsearch's next lifecycle check (every 10 minutes) |
| `HIGH_VOLUME_SOURCES` (a source joins or leaves the shorter tier) | **New** indices. Add `--reassign` to move existing ones too |
| `INDEX_SHARDS`, `INDEX_REPLICAS` | **New** indices only (shard count cannot change on an existing index) |

> **Shortening retention deletes data.** Lowering `LOG_RETENTION_DAYS` (or
> moving a source into a shorter tier with `--reassign`) means Elasticsearch
> deletes every index older than the new value within about 10 minutes. The
> script lists exactly which indices would go and refuses to continue until you
> add `--confirm-shrink`. The same safeguard applies when it is about to attach
> a policy to old indices that were never under one. Snapshot first if you may
> need the data (see [Backups](#backups)).

`--reassign` moves indices between TLSOC's own policies only; an index you put on
a policy of your own is never touched.

## Will it fit on my disk?

Retention is a promise about **time**; the disk has a limit in **bytes**.
Estimate before you commit:

```
disk needed  ≈  (GB written per day)  ×  (days kept)
```

Chatty sources dominate. A proxy (Squid) and a DNS resolver in a campus
network can easily write tens of GB per day between them, while authentication,
mail and web-server logs are small. As an illustration, if all sources together
wrote 60 GB per day, 5 days would need 300 GB but 180 days would need about
**10.8 TB**.

Do not guess: let the stack measure itself. After it has collected for a few
days:

```bash
./elasticsearch/retention_report.py            # average of the last 3 full days
./elasticsearch/retention_report.py --days 7
```

It prints GB per day for every source, the projected size at your configured
retention, and compares that with the disk Elasticsearch actually has, aiming to
stay under 70 % full. If it does not fit, it tells you the options, cheapest
first, and the exact `.env` lines for the first one. They are, in order:

1. **Shorter tier for the heavy sources.** Put them in `HIGH_VOLUME_SOURCES`
   with a shorter `HIGH_VOLUME_RETENTION_DAYS`, and keep the full 180 days for
   everything that matters most for investigations (authentication, mail, web,
   WAF, IDS, cloud audit logs). Then run `setup_storage.py --reassign`.
2. **More disk**, or a larger volume for Docker's data directory.
3. **Less volume at the source.** In the engine's `config.yaml`,
   `output.include_original: false` roughly halves index size (the parsed fields
   are unaffected). Noisy sources can also be filtered before they reach Kafka.

Remember that if a source needs the legal minimum, shortening it is a
compliance decision, not just a storage one: prefer more disk, or ship that
source's older data to cheaper storage (see [Backups](#backups)).

## Keep storage healthy

- **Stay under about 70 % disk used.** Elasticsearch stops allocating new
  shards at 85 %, tries to move data at 90 %, and at **95 %** (the flood-stage
  watermark) makes indices read-only, which stops ingestion. Retention exists to
  keep you well away from that.
- **Re-run the report** when you add a log source, after onboarding a busy
  server, and once a quarter.
- **Watch the dashboard.** The *Storage used* tile and the *Elasticsearch*
  row in *Infrastructure components* turn amber/red before it is an outage.
- **Leave replicas at 0** on this single-node stack (see
  [Settings](#settings)); the cost of a node failure is covered by backups, not
  replicas.
- **Large sources:** one primary shard per daily index is right up to roughly
  50 GB per source per day. Above that, raise `INDEX_SHARDS` (new indices only).
- **Warm-phase compaction** (day 7 by default) rewrites each index once into a
  single, better-compressed segment. This costs some CPU and disk I/O for a
  while per large index; raise `WARM_AFTER_DAYS` if a very busy server is
  sensitive to that.

Check what is happening. The `curl` examples in this guide are run from the
repository directory after loading your settings once per shell:
`set -a; . ./.env; set +a`.

```bash
# which policy and phase each index is in
curl -s --cacert certs/ca/ca.crt -u elastic:$ELASTIC_PASSWORD \
  "https://$HOST_IP:9200/fosstlsoc-logs-*/_ilm/explain?filter_path=indices.*.policy,indices.*.phase,indices.*.age" \
  | python3 -m json.tool | head -40

# size per index, biggest first
curl -s --cacert certs/ca/ca.crt -u elastic:$ELASTIC_PASSWORD \
  "https://$HOST_IP:9200/_cat/indices/fosstlsoc-*?v&h=index,docs.count,store.size&s=store.size:desc" | head
```

## Edit field mappings and index settings

Field types come from the TLSOC Engine's index template (every field the engine
can emit: dates, IPs, `geo_point`, numbers; every text field is a `keyword` that
also has a `.keyword` sub-field, which the reports and dashboards rely on). The
installer layers it with the retention and shard settings above:

```
tlsoc-logs-mappings   (field types, from the engine)     ┐
tlsoc-logs-settings   (shards, replicas, ILM policy)     ├── index template  tlsoc-logs
tlsoc-logs@custom     (YOURS, optional, applied last)    ┘   for fosstlsoc-logs-*
```

**Do not edit the `tlsoc-*` templates directly:** `setup_storage.py` rewrites
them from `.env` each time it runs. Put your changes in the optional component
template `tlsoc-logs@custom`, which the script never creates, changes or
deletes, and which is applied last, so it wins.

Example: map a custom field as an IP and refresh every 5 seconds instead of 30:

```bash
curl -s --cacert certs/ca/ca.crt -u elastic:$ELASTIC_PASSWORD -X PUT \
  "https://$HOST_IP:9200/_component_template/tlsoc-logs@custom" \
  -H 'Content-Type: application/json' -d '{
  "template": {
    "settings": { "index": { "refresh_interval": "5s" } },
    "mappings": { "properties": { "my_app.client_ip": { "type": "ip" } } }
  }
}'
```

It applies to indices created **after** the change (the next day's index). To see
the result before it happens:

```bash
curl -s --cacert certs/ca/ca.crt -u elastic:$ELASTIC_PASSWORD -X POST \
  "https://$HOST_IP:9200/_index_template/_simulate_index/fosstlsoc-logs-nginx-2099.01.01" | python3 -m json.tool | less
```

Other things to know:

- **Existing indices keep the mapping they were created with.** A field's type
  cannot be changed in place; fix it going forward and, if you must, reindex the
  old data.
- **New log source with new fields?** Add the field in the engine's rule and
  regenerate the engine's template (`python3 elasticsearch/generate_template.py`
  in the engine repository), then copy it over the bundled
  `elasticsearch/soc-index-template.json` here (or let the installer use the
  engine installed at `/etc/foss-soc-engine`, which it prefers) and run
  `./elasticsearch/setup_storage.py`.
- **Overlapping templates:** if you have your own index template matching
  `fosstlsoc-logs-*` with a *higher priority* than ours (ours: 300, high-volume
  tier: 400), yours wins and ours is ignored for those indices. Check with
  `GET _index_template` before wondering why a setting did not apply.
- **Index patterns:** the retention policy attaches by index name
  (`fosstlsoc-logs-*`). If you rename the Logstash index pattern, update the
  patterns in `elasticsearch/setup_storage.py` too.

## What gets created

`setup_storage.py` (run by `install.sh` and `dashboards.sh`) is idempotent and
creates or updates:

| Kind | Name | Purpose |
|---|---|---|
| ILM policy | `tlsoc-logs` | hot → warm (compaction) → delete |
| ILM policy | `tlsoc-logs-highvolume` | same, shorter retention (only if `HIGH_VOLUME_SOURCES` is set) |
| ILM policy | `tlsoc-health` | delete health data after `HEALTH_RETENTION_DAYS` |
| Component template | `tlsoc-logs-mappings` | field types from the engine's template, plus `service_name` |
| Component template | `tlsoc-logs-settings` | shards, replicas, 30 s refresh, ILM policy |
| Component template | `tlsoc-logs-hv-lifecycle` | switches the policy for high-volume sources |
| Index template | `tlsoc-logs` | `fosstlsoc-logs-*` (priority 300) |
| Index template | `tlsoc-logs-hv-<source>` | `fosstlsoc-logs-<source>-*` (priority 400), one per high-volume source |
| Index template | `tlsoc-threat-intel` | field types for IOC documents |
| Index | `fosstlsoc-logs-_seed` | empty; lets Kibana resolve all fields before any log arrives (no policy, never deleted) |
| Index | `tlsoc-threat-intel` | empty at first, same reason |

The health collector's own template (`tlsoc-health`) is installed by
`monitoring/` and points at the `tlsoc-health` policy.

### Threat-intelligence data

`tlsoc-threat-intel` is a single index whose documents are keyed by indicator
(so a re-read updates rather than duplicates). ILM deletes whole indices by age,
so it cannot expire individual old indicators. If you want to drop stale IOCs,
delete by query, for example everything last seen more than a year ago:

```bash
curl -s --cacert certs/ca/ca.crt -u elastic:$ELASTIC_PASSWORD -X POST \
  "https://$HOST_IP:9200/tlsoc-threat-intel/_delete_by_query" \
  -H 'Content-Type: application/json' \
  -d '{"query":{"range":{"@timestamp":{"lt":"now-365d"}}}}'
```

## Backups

Retention deletes data; it is not a backup, and a single node is a single point
of failure. If your obligations or your own policy require logs to survive a
disk failure, take Elasticsearch **snapshots** to storage that is not this
disk (a mounted share or an S3-compatible bucket) with a snapshot lifecycle
policy, and keep them for as long as your rules require. Setting this up depends
on your storage, so it is not automated here; see Elastic's
[snapshot and restore documentation](https://www.elastic.co/guide/en/elasticsearch/reference/8.19/snapshot-restore.html).
Take a snapshot before shortening retention.

## When the disk fills up

Symptoms: Logstash logs `cluster_block_exception` / "read-only" errors, the
*Storage used* tile is red, and events stop arriving.

1. Free space: lower retention (see the warning above) or delete the oldest
   indices you can afford to lose:

   ```bash
   curl -s --cacert certs/ca/ca.crt -u elastic:$ELASTIC_PASSWORD -X DELETE \
     "https://$HOST_IP:9200/fosstlsoc-logs-squid-2026.01.01"
   ```

2. Once usage is back under 90 %, Elasticsearch releases the read-only block
   itself. If an index stays blocked:

   ```bash
   curl -s --cacert certs/ca/ca.crt -u elastic:$ELASTIC_PASSWORD -X PUT \
     "https://$HOST_IP:9200/fosstlsoc-logs-*/_settings" \
     -H 'Content-Type: application/json' \
     -d '{"index.blocks.read_only_allow_delete": null}'
   ```

3. Prevent a repeat: run `./elasticsearch/retention_report.py` and apply its
   advice.

## Adopting an existing installation

On a stack that already holds data:

```bash
git pull
sudo ./dashboards.sh
```

What happens to what is already there:

- **Indices already on a policy** (yours or an earlier one, such as a short
  custom policy): left exactly as they are.
- **Indices with no policy:** attached to the new one. If any are older than the
  new retention they would be deleted, so the script lists them and stops until
  you pass `--confirm-shrink`; run it by hand:
  `./elasticsearch/setup_storage.py --confirm-shrink`, or first raise
  `LOG_RETENTION_DAYS`.
- **Your own index template** for `fosstlsoc-logs-*` at a higher priority keeps
  winning. Either keep it (and its policy) or delete it and let the shipped
  templates take over.
- **Replicas:** existing indices with replicas on this single-node stack are set
  to 0 so the cluster can turn green.

Before moving a small server to the 180-day default, run
`./elasticsearch/retention_report.py`: a disk sized for 5 days of data will not
hold 180.
