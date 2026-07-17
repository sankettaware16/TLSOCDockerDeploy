# Contributing to TLSOC Docker Deploy

Thank you for helping improve the TLSOC deployment stack. Ecosystem-wide
guidelines live in
[tlsoc — CONTRIBUTING](https://github.com/sankettaware16/tlsoc/blob/main/CONTRIBUTING.md);
this file covers what is specific to this repository.

## Ground rules

- Be respectful — participation is governed by the
  [Code of Conduct](CODE_OF_CONDUCT.md).
- **Never include real deployment data** in issues, commits, or docs: no real
  IP addresses, hostnames, organization names, passwords, or certificates. Use
  placeholders (`203.0.113.10`, `example_org`, `<server-ip>`).
- Security vulnerabilities go through [SECURITY.md](SECURITY.md), never public
  issues.
- Contributions are accepted under the [Apache-2.0 license](LICENSE).

## What this repository owns

- `docker-compose.yml`, `.env.example`, `install.sh` — the stack itself
- `certs/generate-certs.sh` — the local CA and certificate generation
- `tlsoc-onboard.sh` — agentless source onboarding
- `logstash/` — pipeline and config
- `kibana/saved_objects/` — importable dashboards

Parsing rules belong in
[tlsoc-engine](https://github.com/sankettaware16/tlsoc-engine); report
definitions in
[tlsoc-reporting](https://github.com/sankettaware16/tlsoc-reporting).

## Testing your changes

There is no automated test suite for infrastructure changes yet — validation is
manual and **must be done on a fresh Ubuntu VM** (the supported target):

1. **Stack changes** (`docker-compose.yml`, `install.sh`, certs): run the full
   install path from the README on a clean VM; confirm all four containers stay
   healthy (`docker ps`), Kibana logs in, and a test message reaches a topic.
2. **Onboarding script changes** (`tlsoc-onboard.sh`): run it on a clean source
   VM against a running stack; confirm the generated config passes
   `rsyslogd -N1`, survives a `logrotate` cycle, and the delivery verification
   marker arrives in Kafka. Test both interactive and non-interactive modes.
3. **Logstash pipeline changes**: place a sample ECS NDJSON file in the bind
   mount, confirm it is indexed and the daily index appears in Kibana.

State what you tested (OS version, fresh/existing VM, scenario) in the pull
request.

## Workflow

1. Open an issue first for anything beyond a small fix.
2. Branch from `main`; keep the diff focused on one topic.
3. Follow the existing shell style (`set -e`, explicit error messages); keep
   the onboarding script's safeguards intact (private ruleset, rotation flags,
   delivery verification).
4. Open a PR with the template and update `CHANGELOG.md` under `[Unreleased]`.
