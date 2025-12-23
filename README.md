# TLSOCDockerDeploy 
**One-Click TLS-Enabled SOC Stack (Kafka + Logstash + Elasticsearch + Kibana)**

This repository provides a **plug-and-play, TLS-secured SOC deployment** using Docker Compose.  
It is designed for **fresh Ubuntu servers**

---

##  Architecture
Logs → Kafka → Logstash → Elasticsearch → Kibana


All internal communication is TLS-encrypted using a **locally generated CA**.

---

##  Supported OS

- Ubuntu **20.04 / 22.04 / 24.04**
- Fresh VM or bare-metal recommended

---

##  Prerequisites (Fresh Ubuntu)

###  Update system
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
sudo systemctl enable docker
docker --version


sudo mkdir -p /usr/local/lib/docker/cli-plugins
sudo curl -SL https://github.com/docker/compose/releases/download/v2.25.0/docker-compose-linux-x86_64 \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

```
## Installation
```bash
cd /opt
sudo git clone https://github.com/sankettaware16/TLSOCDockerDeploy.git
cd TLSOCDockerDeploy
./certs/generate-certs.sh <ip server>

sudo cp .env.example .env
nano .env  #update the ip
sudo chmod +x install.sh
sudo ./install.sh

```

## IMPORTANT: First-Time Password Fix (Mandatory)

On first run, Kibana may fail authentication with Elasticsearch.
```bash
#--------FOR KIBANA----------------

docker exec -it elasticsearch \
  /usr/share/elasticsearch/bin/elasticsearch-reset-password \
  -u kibana_system \
  --url https://elasticsearch:9200 \
  -E xpack.security.http.ssl.verification_mode=certificate
#--------FOR ELASTIC----------------
docker exec -it elasticsearch \
  /usr/share/elasticsearch/bin/elasticsearch-reset-password \
  -u elastic \
  --url https://elasticsearch:9200 \
  -E xpack.security.http.ssl.verification_mode=certificate

#copy the pass into env for both elastic and kibana_system
it will look like
Password for the [kibana_system] user successfully reset.
New value: randompass
```
### ADDING PASSWORD TO ENVIRONMENT
```bash
sudo nano .env
```
change the password which you get from the above code
for both elastic and kibana
```bash
ELASTIC_PASSWORD=ChangeThisElasticPassword
KIBANA_PASSWORD=ChangeThisKibanaPassword
```
## RESTART STACK
```bash
docker compose down
docker compose up -d
docker ps
```

to check logs for each component
```bash
docker logs kibana -f
docker logs logstash -f
docker logs elasticsearch -f
docker logs kafka -f
```

### ACCESS KIBANA FROM WEB
```bash
https://<ip-addr>:5601/

```
