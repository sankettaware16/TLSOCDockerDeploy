# Changelog

All notable changes to TLSOC Docker Deploy are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this repository adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **One Kafka topic per log source, connected by name.** Each source has one name
  used end to end: rsyslog tag → topic `tlsoc.logs.<source>` → the TLSOC Engine
  rule with `source: <source>` → index `fosstlsoc-logs-<source>-*`. Topics are
  **not** created in advance: a source's first line creates its topic with
  `KAFKA_DEFAULT_PARTITIONS` (`.env`, default 1, safe for every parser), so Kafka
  holds only the sources that really send, however many parsers exist.
  `kafka/setup-topics.sh` (cron every 5 minutes, installed by `install.sh`)
  gives existing topics the partitions/retention in `kafka/topics.conf` (6 for
  squid and dns, 3 for other busy sources, `*` for a default); `--list`,
  `--dry-run`, `--create <source>`, and `--remove-unused` to delete TLSOC topics
  that never held a message (from an earlier version that created them all).
  It never lowers partitions. Guide: `docs/sources-and-topics.md`.
- `tlsoc-onboard.sh`: `TLSOC_EXTRA_SOURCES="/path/file=name ..."` adds custom files
  without prompts.
- Health collector: Kafka lag per topic (`kafka.max_lag_topic`,
  `kafka.max_topic_lag`, `kafka.topics`), so the status names the source that is
  behind.

### Changed

- **`tlsoc-onboard.sh` no longer asks for a topic.** Each file goes to
  `tlsoc.logs.<source name>` (`dynaTopic`). Discovered files get the standard
  source names the engine has parsers for (`auth.log` → `auth`, `mail.log` →
  `postfix`, nginx access and error logs → `nginx`, plus `/var/log/secure`,
  `/var/log/maillog`, Suricata `fast.log`), and sources without a parser are
  marked. Several files may share a source name; names are lowercased.
  `TLSOC_TOPIC=<topic>` keeps the old single-topic behaviour.
- Onboarding sets `partitions.auto="on"`: without it omkafka wrote every message
  to partition 0, so extra partitions and engine workers were never used. The
  message key is no longer set.
- Logstash `all.conf` maps per-worker engine files (`squid.w0.json`) to the
  source's index (`fosstlsoc-logs-squid-*`); before, a multi-worker engine
  produced indices such as `fosstlsoc-logs-squid.w0-*`.
- **Upgrading:** existing onboarded servers keep sending to their topic and keep
  working (the engine can consume both, see the engine's upgrading guide §8).
  Re-run `tlsoc-onboard.sh` on a server to move it to per-source topics.

### Security

- Removed the hardcoded Kibana `xpack.encryptedSavedObjects.encryptionKey` from
  `docker-compose.yml`. `install.sh` now generates a random key per install and
  stores it in `.env` as `KIBANA_ENCRYPTION_KEY`; the stack refuses to start
  without it. **Existing deployments:** the old key was public, so rotate it.
  Re-run `./install.sh` to generate a new key (existing encrypted saved objects
  such as alerting rules and connectors must then be recreated), or set
  `KIBANA_ENCRYPTION_KEY` in `.env` to your current key to keep them.
- Logstash verifies the Elasticsearch certificate against the local CA and
  reads the password from `ELASTIC_PASSWORD`; no credentials in pipeline files.

### Changed

- **No manual first-start steps.** `install.sh` now generates random
  `elastic` / `kibana_system` passwords (stored only in `.env`, `chmod 600`),
  starts Elasticsearch first, sets the `kibana_system` password itself, applies
  retention and templates, starts the rest of the stack, and imports the
  dashboard. The old "first-time password setup (mandatory)" procedure is gone.
  **Upgrading:** existing `.env` values are never overwritten.
- `install.sh` is safe to re-run: valid existing certificates are kept (they were
  regenerated every time before) and initialised stacks keep their passwords.
- **Log retention is now managed (default 180 days).** Previously nothing expired
  the data. See "Added" below. **Upgrading:** check disk first with
  `./elasticsearch/retention_report.py`; a disk sized for a few days of data will
  not hold 180. Shortening retention or attaching a policy to old indices that
  had none refuses to run without `--confirm-shrink`.
- **Logstash pipeline replaced** (`kafka-to-es.conf` → `all.conf`): indices are
  now `fosstlsoc-logs-<service>-YYYY.MM.dd`, derived from the engine's output
  file names, so new sources need no Logstash change. Rotation-aware tailing,
  persistent read positions, engine `host.name` preserved, tuned batch size.
  Reports, benchmarks and dashboards already query `fosstlsoc-logs-*`; the
  bundled Kibana data view is updated accordingly. **Upgrading:** existing
  `all-logs-*` indices stay in place and remain searchable; new events go to
  `fosstlsoc-logs-*`.
- Kafka upgraded to `apache/kafka:4.2.0` with `LogAppendTime` message
  timestamps.
- Kafka topic data and Logstash read positions are stored in named volumes
  (`kafkadata`, `logstashdata`). **Upgrading:** Kafka's previous data lived in
  the container's writable layer, so recreating the container starts with an
  empty topic buffer. Do it when engine consumer lag is 0.
- All services restart automatically (`unless-stopped`) and their container
  logs are rotated (200 MB x 3).
- The engine output folder is now `ENGINE_OUTPUT_DIR` in `.env` (default
  `/var/log/soc_output`, the engine's default) instead of the fixed
  `/etc/parser_service/output`. **Upgrading:** set `ENGINE_OUTPUT_DIR` to your
  engine's `paths.output_dir`.
- Joined the unified TLSOC ecosystem: standardized README, branding, and
  cross-repository links. The component is presented as **TLSOC Docker Deploy**;
  the repository name (`TLSOCDockerDeploy`) and the `/opt/TLSOCDockerDeploy`
  install path are unchanged.
- Documentation reorganized into `docs/`: installation, onboarding, stack
  architecture, and the Kafka admin cheat sheet.

### Added

- **Data retention and index templates** (`elasticsearch/`): ILM policies
  `tlsoc-logs` (hot → warm compaction → delete, default 180 days per the CERT-In
  Directions of 28 April 2022), `tlsoc-logs-highvolume` (optional shorter tier for
  chatty sources) and `tlsoc-health`; component and index templates layering the
  TLSOC Engine's field types with shard/replica/lifecycle settings; an optional
  operator-owned `tlsoc-logs@custom` override; `setup_storage.py` (idempotent,
  `--dry-run`, `--reassign`, `--confirm-shrink`) and `retention_report.py`
  (does retention fit the disk?). Guide: `docs/retention-and-storage.md`.
- **`dashboards.sh`**: one idempotent command that installs or repairs the
  dashboard, base indices, health collector and Kibana space; the installer
  schedules automatic retries (root) when the first attempt fails, and the job
  removes itself on success or after 24 hours. Guide: `docs/dashboards.md`.
- Dashboards work on an empty install: empty base indices
  (`fosstlsoc-logs-_seed`, `tlsoc-threat-intel`) carry the field lists, and
  `service_name` and the threat-intel fields are mapped up front.
- Health collector: Kafka consumer group is read from the engine's
  `config.yaml`; an engine that is not installed yet is shown as `not-installed`
  and no longer turns the overall status red; also finds an engine installed
  in `/etc/foss-soc-engine`.
- Health monitoring and the "TLSOC - SOC Overview" Kibana dashboard
  (`monitoring/`, `kibana/`), set up automatically by `install.sh`.
- Optional threat-intelligence collectors (`intel/`): AbuseIPDB, AlienVault OTX,
  OpenPhish and MISP, indexed into `tlsoc-threat-intel` by a dedicated Logstash
  pipeline with duplicate-free document ids.
- Apache-2.0 `LICENSE`.
- Community health files: contributing guide, security policy, code of conduct,
  issue templates, and a pull request template.
- Component roadmap (`docs/roadmap.md`).
