# Changelog

All notable changes to TLSOC Docker Deploy are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this repository adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

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

- Health monitoring and the "TLSOC - SOC Overview" Kibana dashboard
  (`monitoring/`, `kibana/`), set up automatically by `install.sh`.
- Optional threat-intelligence collectors (`intel/`): AbuseIPDB, AlienVault OTX,
  OpenPhish and MISP, indexed into `tlsoc-threat-intel` by a dedicated Logstash
  pipeline with duplicate-free document ids.
- Apache-2.0 `LICENSE`.
- Community health files: contributing guide, security policy, code of conduct,
  issue templates, and a pull request template.
- Component roadmap (`docs/roadmap.md`).
