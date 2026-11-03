# Log sources and Kafka topics

Every log source in TLSOC has **one name**, and that name connects everything:

```
/var/log/nginx/access.log
   └─ rsyslog tag      nginx
      └─ Kafka topic   tlsoc.logs.nginx
         └─ parser     the engine rule that declares  source: "nginx"
            └─ index   fosstlsoc-logs-nginx-YYYY.MM.dd  →  dashboards, reports
```

You never choose a topic name, and you never connect a topic to a parser by
hand. Kafka creates a source's topic when its first line arrives, the TLSOC
Engine subscribes to every `tlsoc.logs.*` topic, and the parser is found by name.

## The three everyday flows

### 1. First-time setup (once, on the TLSOC server)

```bash
sudo ./install.sh                       # this repository
```

Besides Elasticsearch, Kibana, Logstash and Kafka, the installer creates the
standard topics listed in [`kafka/topics.conf`](../kafka/topics.conf)
(`tlsoc.logs.auth`, `tlsoc.logs.nginx`, `tlsoc.logs.squid`, ...) with a
partition count that suits each source. Then install the
[TLSOC Engine](https://github.com/sankettaware16/foss-soc-engine); its default
`config.yaml` already consumes `tlsoc.logs.*`, so only the Kafka address needs
setting. Check everything with:

```bash
cd /etc/foss-soc-engine && python3 sources.py
```

Every source shows **WAITING** until its first logs arrive.

### 2. Onboarding a server

On the server whose logs you want, run [`tlsoc-onboard.sh`](onboarding.md). It
asks for the TLSOC server's IP — no topic — and shows what it found:

```
 1) /var/log/auth.log          -> auth      SSH / sudo / logins (high value)
 2) /var/log/nginx/access.log  -> nginx     Nginx access
 3) /var/log/nginx/error.log   -> nginx     Nginx errors
 4) /var/log/mail.log          -> postfix   Mail / postfix
```

Each file goes to the topic of its name (`auth` → `tlsoc.logs.auth`). Within
about 30 seconds the engine picks the new topics up, parses each source with its
rule, and the events appear in `fosstlsoc-logs-<source>-*`. `sources.py` shows
the rows turning **OK**.

- **A file no parser exists for yet** (say `/var/log/moodle.log`): give it a name
  when the script asks (`moodle`). Its topic is created automatically and the
  engine keeps every line in its dead-letter file `logs/dlq/moodle.json`;
  `sources.py` shows **NO PARSER**. Nothing is lost — see flow 3.
- **Network devices and appliances** that can only send syslog: send them to a
  central rsyslog server and tag each device type with its source name there;
  the same per-source topic rule applies.
- **Cloud services** (Okta, Google Workspace): [Siphon](https://github.com/trustlab-org/siphon)
  sends to `tlsoc.logs.okta` / `tlsoc.logs.google_workspace` by default.
- **Other shippers** (Vector, Fluent Bit, Filebeat ...): send the plain lines to
  `tlsoc.logs.<source>`; the topic names the source, so the `{meta, raw}`
  envelope is optional.

### 3. Writing a parser for a new service

1. Take sample lines from `logs/dlq/moodle.json` — they are the real lines that
   arrived while there was no parser.
2. Write `rules/moodle.yaml` with `source: "moodle"` at the top
   ([writing rules](https://github.com/sankettaware16/foss-soc-engine/blob/main/docs/writing-rules.md)).
3. Test it: `python3 test_file.py sample.log moodle`.
4. Save it. The running engine loads it within about 10 seconds — no restart —
   and Moodle lines are parsed from then on into `fosstlsoc-logs-moodle-*`.
5. Share it with a pull request (rule + sample lines) so every TLSOC
   installation gets it, and onboarding recognises the source next time.

## Names

The standard names are the `source:` of the shipped engine rules: `auth`,
`nginx`, `apache`, `squid`, `dns`, `postfix`, `radius`, `sso`, `policyd_spf`,
`suricata`, `modsec`, `fim`, `nessus`, `openvas`, `roundcube`. Rules also accept
common aliases (`sshd` → auth, `mail` → postfix, `dnsdist` → dns, `httpd` →
apache, ...). A name of your own is fine for anything else: lowercase letters,
digits, `_` and `-`. The name is also the index name part, so it is what
dashboards, reports and retention settings (`HIGH_VOLUME_SOURCES=squid,dns`)
refer to.

A tag that only makes sense at your site can be mapped to a parser in the
engine's `config.yaml` → `program_mapping` (e.g. `fmlr: "policyd_spf"`).

## Topics and partitions

[`kafka/topics.conf`](../kafka/topics.conf) lists the standard topics:

```
# source        partitions  [retention_hours]
auth            3
squid           6
dns             6
postfix         1
```

- **Partitions** are how many engine workers can share one source. Give busy
  sources more. Raising later is fine; Kafka can never lower it. Keep **1** for
  sources whose rule joins several lines of one transaction (postfix).
- **Retention** (optional third column, hours) is how long Kafka keeps messages
  as a buffer while the engine is down. Default: the broker's 168 hours.
- A source not listed gets its topic on first use with
  `KAFKA_DEFAULT_PARTITIONS` partitions (`.env`, default 3).

Apply changes (safe to repeat; never deletes or shrinks anything):

```bash
sudo ./kafka/setup-topics.sh             # create / upgrade
sudo ./kafka/setup-topics.sh --dry-run   # show what would change
sudo ./kafka/setup-topics.sh --list      # topics and partitions
```

To use more CPU cores, raise the engine's `runtime.workers`; a worker only gets
work if there are enough partitions to go round.

## Why one topic per source

Measured on one laptop with a realistic mix (squid 56 %, dns 37 %, sso 5 %, the
rest 2 %), engine `main` vs this layout:

| | One shared topic, 1 worker | Per-source topics, 1 worker | Per-source topics, 4 workers |
|---|---|---|---|
| Throughput (600k messages) | ~15k events/s | ~15k events/s | ~37k events/s |
| sso delay while 400k squid lines arrive at once | up to **24 s** | ≤ **1.4 s** | ≤ **0.5 s** |
| Lag visible per source | no | yes | yes |

- A burst from one source no longer delays the others.
- Busy sources can use several workers.
- `sources.py` and the health dashboard show which source is behind.
- Retention and partitions can differ per source.

Both layouts lost nothing when the engine was killed (`kill -9`) or Kafka was
restarted mid-stream.

## Older single-topic installations

A setup that sends everything to one topic (for example `logservercc`) and
routes with `program_mapping` keeps working unchanged. To move over, see the
engine's [upgrading guide §8](https://github.com/sankettaware16/foss-soc-engine/blob/main/docs/upgrading.md).
Onboarding can still write the old style: `TLSOC_TOPIC=<topic> sudo bash tlsoc-onboard.sh`.

## Troubleshooting

| `sources.py` shows | Meaning / fix |
|---|---|
| WAITING | No data yet. On the sending server: `sudo journalctl -u rsyslog -f`; check it reaches port 9094 |
| NO PARSER | Data arrives, no rule declares this name. Write one (flow 3), or map the tag in `program_mapping` if a rule already fits |
| BEHIND | More than 100k messages waiting. Raise `runtime.workers` (and the topic's partitions) |
| DLQ | Recent lines the rule did not match: look at `logs/dlq/<source>.json` and extend the rule |
| Source missing from the list | Its topic does not match the engine's `input_topic`; keep the default `^tlsoc\.logs\..+$` |
