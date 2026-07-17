# Installation

Complete installation guide for the TLSOC core stack on a fresh Ubuntu server.

## Supported OS

- Ubuntu **20.04 / 22.04 / 24.04**
- Fresh VM or bare metal recommended

## Prerequisites

### Update the system

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y \
  ca-certificates \
  curl \
  gnupg \
  lsb-release \
  git \
  openssl
```

### Install Docker and Docker Compose

```bash
curl -fsSL https://get.docker.com | sudo bash
sudo systemctl enable docker
sudo systemctl start docker
docker --version

sudo mkdir -p /usr/local/lib/docker/cli-plugins
sudo curl -SL https://github.com/docker/compose/releases/download/v2.25.0/docker-compose-linux-x86_64 \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
```

## Install the stack

```bash
cd /opt
sudo git clone https://github.com/sankettaware16/TLSOCDockerDeploy.git
cd TLSOCDockerDeploy
sudo chmod +x install.sh
sudo ./install.sh
```

`install.sh` performs the whole first bring-up:

1. Verifies Docker and Docker Compose are present.
2. Creates `.env` from `.env.example` if missing.
3. Auto-detects the host IP and writes it to `.env` (`HOST_IP`) — set it
   yourself in `.env` first if the machine has multiple interfaces.
4. Generates the local CA and per-service TLS certificates
   (`certs/generate-certs.sh <ip>`).
5. Starts the stack with `docker compose up -d`.

To regenerate certificates later (for example after an IP change), run
`./certs/generate-certs.sh <server-ip>` and restart the stack.

> **Installing somewhere other than `/opt/TLSOCDockerDeploy`?** That works, but
> note that
> [tlsoc-reporting-framework](https://github.com/sankettaware16/tlsoc-reporting-framework)
> auto-detects the stack at `/opt/TLSOCDockerDeploy` by default — point its
> `tlsoc_deploy.dir` setting at your location.

## First-time password setup (mandatory)

On first run, Kibana may fail authentication with Elasticsearch. Reset both
built-in users and store the generated passwords in `.env`:

```bash
# -------- for kibana_system --------
docker exec -it elasticsearch \
  /usr/share/elasticsearch/bin/elasticsearch-reset-password \
  -u kibana_system \
  --url https://elasticsearch:9200 \
  -E xpack.security.http.ssl.verification_mode=certificate

# -------- for elastic --------
docker exec -it elasticsearch \
  /usr/share/elasticsearch/bin/elasticsearch-reset-password \
  -u elastic \
  --url https://elasticsearch:9200 \
  -E xpack.security.http.ssl.verification_mode=certificate
```

Each command prints a line like:

```
Password for the [kibana_system] user successfully reset.
New value: <generated-password>
```

Copy both generated passwords into `.env`:

```bash
sudo nano .env
```

```bash
ELASTIC_PASSWORD=<generated elastic password>
KIBANA_PASSWORD=<generated kibana_system password>
```

Restart the stack so the new credentials take effect:

```bash
docker compose down
docker compose up -d
docker ps
```

## Verify

```bash
# Per-service logs
docker logs kibana -f
docker logs logstash -f
docker logs elasticsearch -f
docker logs kafka -f
```

Open Kibana from a browser:

```
https://<server-ip>:5601/
```

Sign in as `elastic` with your `ELASTIC_PASSWORD`.

## Configuration reference (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `ELASTIC_VERSION` | `8.19.12` | Elastic Stack image version (Elasticsearch, Kibana, Logstash) |
| `ELASTIC_PASSWORD` | — | `elastic` superuser password (set after first-time reset) |
| `KIBANA_PASSWORD` | — | `kibana_system` password (set after first-time reset) |
| `ELASTIC_HEAP` | `1g` | Elasticsearch JVM heap size |
| `KIBANA_PORT` | `5601` | Kibana HTTPS port |
| `HOST_IP` | auto-detected | The server IP baked into certificates and external listeners |

## Next steps

1. [Onboard log sources](onboarding.md) — start forwarding logs from your
   servers.
2. Install [foss-soc-engine](https://github.com/sankettaware16/foss-soc-engine) to
   parse and normalize the forwarded logs; Logstash tails its output directory
   (`/etc/parser_service/output` on the host — see
   [architecture.md](architecture.md#logstash-pipeline)) and indexes into
   Elasticsearch.
3. Set up [tlsoc-reporting-framework](https://github.com/sankettaware16/tlsoc-reporting-framework)
   for daily HTML/PDF reports.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Kibana login loop or 401 | Passwords in `.env` don't match Elasticsearch — redo the [password setup](#first-time-password-setup-mandatory) and restart |
| Browser certificate warning | Expected: the stack uses a locally generated CA. Import `certs/ca/ca.crt` into your browser/OS trust store to remove it |
| Onboarded server's logs never arrive | Check connectivity to `:9094`, then `sudo journalctl -u rsyslog -f` on the source; see [onboarding.md](onboarding.md) |
| Logstash indexes nothing | The engine output bind mount is empty — confirm TLSOC Engine writes to the directory mounted as `/parser_output` |
| `elasticsearch` container restarts / OOM | Raise `ELASTIC_HEAP` in `.env` and ensure the VM has enough RAM |
