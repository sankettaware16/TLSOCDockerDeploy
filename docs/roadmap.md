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
- Kafka admin cheat sheet and importable Kibana saved objects.

## Next Release

- Ecosystem alignment: standardized documentation, community health files, and
  release tagging (this refactoring).
- Automated first-start password initialization (remove the manual
  `elasticsearch-reset-password` step).
- Health-check script for the whole stack (containers, certs, ports, disk).

## Future

- Multi-node Elasticsearch profile (dedicated data/master layout).
- Kafka TLS client-authentication option for onboarded servers.
- Bundled Kibana dashboard pack for the engine's ECS output.
- Automated certificate rotation.

## Long Term Vision

- Turn-key appliance image (preinstalled stack + engine + reporting).
- Optional orchestration targets beyond Compose (e.g. single-node k3s) if
  demand justifies them.

## Proposing changes

Open a [feature request](https://github.com/sankettaware16/TLSOCDockerDeploy/issues) using the template. Roadmap changes land
here via pull request.
