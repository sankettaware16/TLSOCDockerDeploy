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
### Onboarding Log Sources (Agentless Forwarding via rsyslog + omkafka)

This stack uses an agentless model: Linux servers forward logs directly using rsyslog + omkafka module → Kafka topic → Logstash → Elasticsearch.

There are **two ways** to onboard a server. The **automated script** is the fastest and is recommended for most servers. The **manual method** is available for advanced or fully custom setups.

---

####  Easiest & Fastest: Automated Onboarding (Recommended)

Onboard any Ubuntu/Linux server in **one command** — no manual config editing. The script asks a few questions, auto-discovers your logs, sets everything up, and verifies delivery to Kafka.

**Run this on the server whose logs you want to forward:**
```bash
# 1. As your normal user (NOT root) — download it:
curl -fsSL https://raw.githubusercontent.com/sankettaware16/TLSOCDockerDeploy/main/tlsoc-onboard.sh -o tlsoc-onboard.sh

# 2. Verify it actually downloaded a script (not an empty/HTML error page):
ls -l tlsoc-onboard.sh
head -5 tlsoc-onboard.sh

# 3. Run it with sudo:
sudo bash tlsoc-onboard.sh
```


**What it does automatically:**
- Installs the `omkafka` module (`rsyslog-kafka`) if missing
- Asks for the **TLSOC server IP** and tests connectivity to port `9094` before continuing
- Asks for the **Kafka topic** and envelope metadata (org / dept / env / server id)
- **Auto-discovers** common logs in `/var/log` (auth, kern, ufw, dpkg, apt, nginx, apache, mail, fail2ban, auditd …) and lets you keep or drop any
- Lets you add **custom log paths** (each verified to exist and be readable first)
- Generates a **hardened, rotation-safe config** and validates it *before* restarting — so it never breaks existing logging
- **Verifies end-to-end delivery** using a unique test marker and prints the exact command to confirm it reached Kafka

**Why use it:**
- One command instead of copy-pasting and hand-editing the config
- Bakes in production safeguards automatically — survives log rotation, avoids replay bursts, and prevents logs from being silently dropped
- Catches common mistakes up front (unreachable broker, unreadable files, message-size truncation)
- Confirms logs are actually arriving in Kafka before you walk away

**Non-interactive mode (for scripted rollouts):**
```bash
TLSOC_IP=<ip> TLSOC_TOPIC=<topic> TLSOC_ORG=<org> TLSOC_DEPT=<dept> \
TLSOC_ENV=production TLSOC_SERVERID=<id> sudo bash tlsoc-onboard.sh
```

---

####  Manual Method (Advanced / Custom Setups)

Steps to Onboard Any Ubuntu/Linux Server
Install the omkafka module (one-time per source server)
```bash
sudo apt update
sudo apt install -y rsyslog-kafka

```
Create the forwarding config file
Create /etc/rsyslog.d/tlsoc_logfwd.conf and paste the template below.
Template (copy-paste this entire block):
```bash
############################################################
# Server → KAFKA (TLSOC) Log Forwarding Configuration
# File Location  : /etc/rsyslog.d/tlsoc_logfwd.conf
# After changes  : sudo rsyslogd -N1  &&  sudo systemctl restart rsyslog
#
# DESIGN NOTE — why the ruleset matters (do not remove it):
# imfile re-injects each line it reads back into the rsyslog
# engine. By default those lines traverse EVERY *.conf ruleset
# on the host (e.g. 50-default.conf's "*.*" catch-all), which
# can silently swallow them into /var/log/syslog BEFORE this
# forwarder runs — and can make a file feed its own output back
# into itself. Binding each input to a private ruleset
# ("toKafka") sends its lines STRAIGHT to Kafka and stops them,
# bypassing all other routing. This is the core safeguard.
############################################################

#############################
# LOAD REQUIRED MODULES
#############################
module(load="imfile" mode="inotify")   # inotify follows files across rename-rotation
module(load="omkafka")

#############################
# KAFKA MESSAGE TEMPLATE
#############################
template(name="KafkaProxyEnvelope" type="list") {
  constant(value="{\"meta\":{")
    constant(value="\"org\":\"xyz_university\",")        # CHANGE IF REQUIRED
    constant(value="\"dept\":\"cse\",")                  # CHANGE REQUIRED
    constant(value="\"env\":\"production\",")            # CHANGE REQUIRED (development/testing/production)
    constant(value="\"server\":\"cse_web_server_1\",")   # CHANGE REQUIRED (unique server identifier)
    constant(value="\"source_host\":\"")
      property(name="hostname")
    constant(value="\",")
    constant(value="\"source_program\":\"")
      property(name="programname")
    constant(value="\"")
  constant(value="},\"raw\":\"")
    property(name="msg" format="json")
  constant(value="\"}\n")
}

#############################
# KAFKA-ONLY RULESET
# Every message entering this ruleset is forwarded to Kafka and
# stopped. Only the imfile inputs below feed it, so no
# $programname filter is needed. To send different sources to a
# DIFFERENT topic, copy this ruleset under a new name (e.g.
# "toKafka_auth") with its own topic, and bind inputs to it.
#############################
ruleset(name="toKafka") {
  action(
    type="omkafka"
    topic="cse_logs"                 # CHANGE REQUIRED → your Kafka topic name
    broker=["<IP-TLSOC>:9094"]       # CHANGE REQUIRED → central Kafka broker IP:port
    key="%programname%"
    template="KafkaProxyEnvelope"
    confParam=[
      "compression.codec=snappy",
      "linger.ms=50",
      "batch.num.messages=1000"
    ]
    action.resumeRetryCount="-1"     # buffer + retry forever if broker is unreachable
  )
  stop
}

#############################
# LOG INPUT CONFIGURATION
# Add one input() block per log file. Each MUST have:
#   ruleset="toKafka"        → routes it straight to Kafka (the safeguard)
#   reopenOnTruncate="on"    → survives copytruncate log rotation
#   freshStartTail="on"      → on FIRST deploy, starts at end-of-file
#                              (no multi-GB replay burst on existing logs).
#                              On later restarts it resumes from saved
#                              offset, so no data is lost. Set to "off"
#                              ONLY if you deliberately want to backfill
#                              an existing file's full history on deploy.
# Give every input a UNIQUE Tag — it becomes source_program in the
# envelope AND the Kafka partition key.
#############################
input(type="imfile"
      File="/location/of/logs/tomcat.log"   # CHANGE REQUIRED → full path to log file
      Tag="web_tomcat_logs"                 # CHANGE REQUIRED → unique tag for this source
      Severity="info"
      Facility="local4"
      ruleset="toKafka"
      reopenOnTruncate="on"
      freshStartTail="on"
      persistStateInterval="200")           # save read-offset every 200 lines (crash safety)

# --- Add more sources the same way (all → same topic, distinguished by Tag) ---
#input(type="imfile"
#      File="/var/log/nginx.log"
#      Tag="nginx"
#      Severity="info"
#      Facility="local4"
#      ruleset="toKafka"
#      reopenOnTruncate="on"
#      freshStartTail="on"
#      persistStateInterval="200")
```
# Save file → Restart rsyslog:
```
sudo systemctl restart rsyslog
sudo journalctl -u rsyslog -f    (look for errors)
```

### Confirming logs are recvied by kafka
on TLSOCDOCKER machine 
```
cd /opt/TLSOCDockerDeploy/
sudo docker exec -it kafka   /opt/kafka/bin/kafka-console-consumer.sh   --bootstrap-server kafka:9092   --topic topic_name(eg: cse_logs)
```
Real-time logs will be received

# Quick TLSOC Kafka Admin Cheat Sheet
```
cd /opt/TLSOCDockerDeploy/
```
### List all topics
```
docker exec -it kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --list
```
### Describe topic
```
docker exec -it kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --describe --topic <topic>

```
### Live watch topic
```
docker exec -it kafka /opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server kafka:9092 --topic <topic>

```
### Read from beginning
```
docker exec -it kafka /opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server kafka:9092 --topic <topic> --from-beginning

```
### Approximate message count
```
docker exec -it kafka /opt/kafka/bin/kafka-run-class.sh kafka.tools.GetOffsetShell --broker-list kafka:9092 --topic <topic>

```
