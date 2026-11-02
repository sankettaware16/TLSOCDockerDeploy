# Threat-intelligence collectors

Optional feeders that pull indicators of compromise (IOCs) from public and
private threat-intelligence feeds into Elasticsearch, so you can search, join
and alert on them next to your logs.

| Collector | Feed | Key needed |
|---|---|---|
| `abuseipdb_collector.py` | [AbuseIPDB](https://www.abuseipdb.com/) high-confidence IP blacklist | `ABUSEIPDB_API_KEY` |
| `otx_collector.py` | [AlienVault OTX](https://otx.alienvault.com/) subscribed pulses | `OTX_API_KEY` |
| `openphish_collector.py` | [OpenPhish](https://openphish.com/) community phishing URLs | none |
| `misp_collector.py` | your [MISP](https://www.misp-project.org/) instance (incremental, paginated) | `MISP_URL`, `MISP_KEY` |

```
feed API ──► collector ──► <engine output>/threat_intel/<feed>.json
                                   │
              Logstash `threat_intel` pipeline (already part of the stack)
                                   ▼
                      Elasticsearch index  tlsoc-threat-intel
```

Each IOC becomes one document with `intel_source`, `ioc_type`, `ioc_value`
and `@timestamp`. The document id is a hash of source + type + value, so a
re-read never creates duplicates, and each collector keeps a "seen" cache in
`intel/cache/` so only new indicators are written.

## Setup

```bash
cd /opt/TLSOCDockerDeploy/intel
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env && nano .env     # add the keys for the feeds you use
./run-all.sh                           # test run
```

`TLSOC_OUTPUT_DIR` must be the folder Logstash reads, which is the engine
output folder (`ENGINE_OUTPUT_DIR` in the stack `.env`). Feeds with an empty
key are skipped.

Schedule it (hourly is plenty for these feeds):

```cron
0 * * * * /opt/TLSOCDockerDeploy/intel/run-all.sh >> /var/log/tlsoc-intel.log 2>&1
```

## Using the data

In Kibana create a data view on `tlsoc-threat-intel`, then search or build
detections that match `ioc_value` against `source.ip`, `destination.ip`,
`url.full` or `dns.question.name` in your `fosstlsoc-logs-*` indices.

## Security

- API keys live only in `intel/.env`, which is git-ignored. Never put keys in
  the scripts.
- `MISP_VERIFY_SSL=false` is for self-signed MISP instances only.
