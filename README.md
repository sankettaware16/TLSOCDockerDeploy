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
# After changes  : sudo systemctl restart rsyslog
############################################################

#############################
# LOAD REQUIRED MODULES
#############################
module(load="imfile")     # Required to read log files
module(load="omkafka")    # Required to forward logs to Kafka

#############################
# KAFKA MESSAGE TEMPLATE
#############################
# Modify ONLY the values marked as CHANGE REQUIRED

template(name="KafkaProxyEnvelope" type="list") {
  constant(value="{\"meta\":{")
  
    constant(value="\"org\":\"xyz_university\",")        # CHANGE IF REQUIRED 
    constant(value="\"dept\":\"cse\",")        # CHANGE REQUIRED
    constant(value="\"env\":\"production\",")  # CHANGE REQUIRED (development/testing/prod)
    constant(value="\"server\":\"cse_web_server_1\",")  # CHANGE REQUIRED (unique server identifier)

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
# LOG INPUT CONFIGURATION
#############################
# UPDATE the File path and Tag

input(type="imfile"
      File="/location/of/logs/tomcat.log"   # CHANGE REQUIRED → actual full path to log file
      Tag="web_tomcat_logs"                 # CHANGE REQUIRED → unique tag for this source
      Severity="info"
      Facility="local4")

# Example: Add more inputs as needed (nginx, auth, etc.)
#input(type="imfile"
#      File="/var/log/nginx/access.log"
#      Tag="nginx_access"
#      Severity="info"
#      Facility="local4")

#############################
# KAFKA FORWARDING RULE
#############################

# $programname must match the Tag from input section above

if $programname == 'web_tomcat_logs' then {    # ← Update to match your Tag
  action(
    type="omkafka"
    topic="cse_logs"                # CHANGE THIS → your Kafka topic_name
    broker=["<IP-TLSOC>:9094"]   # ← Usually kept as-is (your central Kafka broker IP:port)
    key="%programname%"
    template="KafkaProxyEnvelope"

    confParam=[
      "compression.codec=snappy",
      "linger.ms=50",
      "batch.num.messages=1000"
    ]

    action.resumeRetryCount="-1"
  )
  stop
}

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
