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

### Changed

- Joined the unified TLSOC ecosystem: standardized README, branding, and
  cross-repository links. The component is presented as **TLSOC Docker Deploy**;
  the repository name (`TLSOCDockerDeploy`) and the `/opt/TLSOCDockerDeploy`
  install path are unchanged.
- Documentation reorganized into `docs/`: installation, onboarding, stack
  architecture, and the Kafka admin cheat sheet.

### Added

- Apache-2.0 `LICENSE`.
- Community health files: contributing guide, security policy, code of conduct,
  issue templates, and a pull request template.
- Component roadmap (`docs/roadmap.md`).
