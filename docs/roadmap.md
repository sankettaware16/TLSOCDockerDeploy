# TLSOC Docker Deploy Roadmap

Component roadmap for the deployment stack. The platform-wide roadmap lives in
[tlsoc — Roadmap](https://github.com/sankettaware16/tlsoc/blob/main/docs/roadmap.md).

## Current

Shipped and maintained:

- One-command installer: IP auto-detection, `.env` creation, local CA and
  per-service certificate generation, compose bring-up.
- TLS-secured Kafka (external listener `:9094`), Logstash, Elasticsearch, and
  Kibana.
- Agentless onboarding script (`tlsoc-onboard.sh`) with log auto-discovery,
  hardened rotation-safe rsyslog configuration, and end-to-end delivery
  verification.
- Kafka admin cheat sheet.
- Generated passwords and automatic `kibana_system` setup (no manual reset step).
- Data retention (ILM) aligned with the CERT-In 180-day requirement, with a
  disk-fit report, a shorter tier for very chatty sources, and a customisation
  hook for templates.
- The *TLSOC - SOC Overview* dashboard and health monitoring, installed
  automatically and repairable with `dashboards.sh` (with automatic retry).
- Optional threat-intelligence collectors (AbuseIPDB, OTX, OpenPhish, MISP).

## Next Release

- Ecosystem alignment: standardized documentation, community health files, and
  release tagging (this refactoring).
- Kafka TLS/SASL on the external listener (today it is plaintext on `:9094`;
  see the open issue).
- Snapshot lifecycle policy for backups of retained logs.

## Future

- Multi-node Elasticsearch profile (dedicated data/master layout).
- Kafka TLS client-authentication option for onboarded servers.
- More bundled dashboards: per-source drill-downs for the engine's ECS output.
- Automated certificate rotation.

## Long Term Vision

- Turn-key appliance image (preinstalled stack + engine + reporting).
- Optional orchestration targets beyond Compose (e.g. single-node k3s) if
  demand justifies them.

## Proposing changes

Open a [feature request](https://github.com/sankettaware16/TLSOCDockerDeploy/issues) using the template. Roadmap changes land
here via pull request.
