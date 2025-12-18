# TLSOCDockerDeploy 
**One-Click TLS-Enabled SOC Stack (Kafka + Logstash + Elasticsearch + Kibana)**

This repository provides a **plug-and-play, TLS-secured SOC deployment** using Docker Compose.  
It is designed for **fresh Ubuntu servers** and tested end-to-end.

---

##  Architecture
Logs → Kafka → Logstash → Elasticsearch → Kibana
(TLS) (TLS) (TLS)

All internal communication is TLS-encrypted using a **locally generated CA**.

---

##  Supported OS

- Ubuntu **20.04 / 22.04 / 24.04**
- Fresh VM or bare-metal recommended

---

##  Prerequisites (Fresh Ubuntu)

###  Update system
sudo apt update && sudo apt upgrade -y
sudo apt install -y \
  ca-certificates \
  curl \
  gnupg \
  lsb-release \
  git \
  openssl

  ### Install Docker and Docker Compose 
  curl -fsSL https://get.docker.com | sudo bash
sudo systemctl enable docker
sudo systemctl start docker
durl -fsSL https://get.docker.com | sudo bash
sudo systemctl enable docker
docker --version


sudo mkdir -p /usr/local/lib/docker/cli-plugins
sudo curl -SL https://github.com/docker/compose/releases/download/v2.25.0/docker-compose-linux-x86_64 \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose


## Installation
cd /opt
sudo git clone https://github.com/sankettaware16/TLSOCDockerDeploy.git
cd TLSOCDockerDeploy
./cert/generate-certs.sh <ip server>

sudo cp .env.example .env
sudo nano .env

change this
ELASTIC_VERSION=8.12.2

ELASTIC_PASSWORD=ChangeThisElasticPassword
KIBANA_PASSWORD=ChangeThisKibanaPassword

ELASTIC_HEAP=4g
KIBANA_PORT=5601

sudo chmod +x install.sh
sudo ./install.sh


## IMPORTANT: First-Time Password Fix (Mandatory)

On first run, Kibana may fail authentication with Elasticsearch.
--------FOR KIBANA----------------
docker exec -it elasticsearch \
  /usr/share/elasticsearch/bin/elasticsearch-reset-password \
  -u kibana_system \
  --url https://elasticsearch:9200 \
  -E xpack.security.http.ssl.verification_mode=certificate

copy the pass into env for both elastic and kibana_system

## RESTART STACK
docker compose down
docker compose up -d
docker ps
