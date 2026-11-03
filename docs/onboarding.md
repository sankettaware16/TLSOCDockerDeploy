# Onboarding Log Sources

TLSOC uses an **agentless** model: Linux servers forward logs directly using
`rsyslog` + the `omkafka` module → Kafka → TLSOC Engine → Logstash →
Elasticsearch. Nothing custom is installed on the source machines beyond an
rsyslog configuration.

Each log source has one name (`auth`, `nginx`, `postfix`, ...) and goes to its
own Kafka topic, `tlsoc.logs.<name>`. The engine reads every such topic and
picks the parser by the same name, so there is **no topic to choose and nothing
to map** — see [Log sources and Kafka topics](sources-and-topics.md).

There are two ways to onboard a server. The **automated script** is the fastest
and is recommended for most servers; the **manual method** is available for
advanced or fully custom setups.

## Automated onboarding (recommended)

Onboard any Ubuntu/Linux server in **one command** — no manual config editing.
The script asks a few questions, auto-discovers your logs, sets everything up,
and verifies delivery to Kafka.

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
- Asks for the **TLSOC server IP** and tests connectivity to port `9094` before
  continuing
- Asks for the envelope metadata (org / dept / env / server id) — **no topic**:
  each file goes to `tlsoc.logs.<source name>`
- **Auto-discovers** common logs in `/var/log` (auth, kern, ufw, dpkg, apt,
  nginx, apache, mail, fail2ban, suricata, auditd, …), names each with its
  standard source name (`auth.log` → `auth`, `mail.log` → `postfix`, nginx access
  and error logs → `nginx`), marks the ones the engine has a parser for, and
  lets you keep or drop any
- Lets you add **custom log paths** with a source name of your choice (each
  verified to exist and be readable first). A source without a parser is still
  forwarded and kept by the engine until a parser is written
- Generates a **hardened, rotation-safe config** and validates it *before*
  restarting — so it never breaks existing logging
- **Verifies end-to-end delivery** using a unique test marker and prints the
  exact command to confirm it reached Kafka

**Why use it:**

- One command instead of copy-pasting and hand-editing the config
- Bakes in production safeguards automatically — survives log rotation, avoids
  replay bursts, and prevents logs from being silently dropped
- Catches common mistakes up front (unreachable broker, unreadable files,
  message-size truncation)
- Confirms logs are actually arriving in Kafka before you walk away

**Non-interactive mode (for scripted rollouts):**

```bash
TLSOC_IP=<ip> TLSOC_ORG=<org> TLSOC_DEPT=<dept> \
TLSOC_ENV=production TLSOC_SERVERID=<id> \
TLSOC_EXTRA_SOURCES="/var/log/moodle.log=moodle /opt/app/app.log=myapp" \
sudo -E bash tlsoc-onboard.sh
```

`TLSOC_EXTRA_SOURCES` adds custom files without prompts (`path=name`, space
separated). Older single-topic setups: `TLSOC_TOPIC=<topic>` sends every source
to that one topic instead of `tlsoc.logs.<name>` (the engine's
`kafka.input_topic` must then include it).

## Manual method (advanced / custom setups)

### 1. Install the omkafka module (one-time per source server)

```bash
sudo apt update
sudo apt install -y rsyslog-kafka
```

### 2. Create the forwarding config file

Create `/etc/rsyslog.d/tlsoc_logfwd.conf` and paste the template below.

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
    constant(value="\"org\":\"example_org\",")           # CHANGE IF REQUIRED
    constant(value="\"dept\":\"it\",")                   # CHANGE REQUIRED
    constant(value="\"env\":\"production\",")            # CHANGE REQUIRED (development/testing/production)
    constant(value="\"server\":\"web_server_1\",")       # CHANGE REQUIRED (unique server identifier)
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
# TOPIC: one per source, tlsoc.logs.<Tag of the input>
#############################
template(name="TlsocTopic" type="string" string="tlsoc.logs.%programname%")

#############################
# KAFKA-ONLY RULESET
# Every message entering this ruleset is forwarded to Kafka and
# stopped. Only the imfile inputs below feed it, so no
# $programname filter is needed. Each message goes to the topic
# named after its input's Tag (tlsoc.logs.nginx, ...).
#############################
ruleset(name="toKafka") {
  action(
    type="omkafka"
    topic="TlsocTopic"
    dynaTopic="on"                   # topic name built per message from the template
    partitions.auto="on"             # spread over all partitions (else all go to partition 0)
    broker=["<IP-TLSOC>:9094"]       # CHANGE REQUIRED → central Kafka broker IP:port
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
# The Tag is the SOURCE NAME: it becomes source_program in the
# envelope, the topic tlsoc.logs.<Tag> and the index
# fosstlsoc-logs-<Tag>-*. Use the engine's name for sources it
# has a parser for (auth, nginx, apache, postfix, squid, dns,
# radius, sso, suricata, modsec ...); several files may share a
# Tag. Lowercase letters, digits, '_' and '-'.
#############################
input(type="imfile"
      File="/location/of/logs/tomcat.log"   # CHANGE REQUIRED → full path to log file
      Tag="tomcat"                          # CHANGE REQUIRED → source name
      Severity="info"
      Facility="local4"
      ruleset="toKafka"
      reopenOnTruncate="on"
      freshStartTail="on"
      persistStateInterval="200")           # save read-offset every 200 lines (crash safety)

# --- Add more sources the same way (each Tag gets its own topic) ---
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

### 3. Save and restart rsyslog

```bash
sudo rsyslogd -N1                  # validate first
sudo systemctl restart rsyslog
sudo journalctl -u rsyslog -f      # look for errors
```

## Confirming logs are received by Kafka

On the TLSOC server:

```bash
cd /opt/TLSOCDockerDeploy/
sudo docker exec -it kafka /opt/kafka/bin/kafka-console-consumer.sh \
  --bootstrap-server kafka:9092 --topic tlsoc.logs.<source>
```

Real-time logs will be received. On the engine host, `python3 sources.py` shows
every source at once (topic, rate, lag, parser). More topic operations:
[kafka-admin.md](kafka-admin.md).

## After onboarding

Each `Tag` arrives at
[foss-soc-engine](https://github.com/sankettaware16/foss-soc-engine) on topic
`tlsoc.logs.<Tag>` and as `meta.source_program`. A standard name is parsed by
its rule straight away; nothing to configure. For a name without a parser, the
engine keeps the lines in `logs/dlq/<Tag>.json` and `sources.py` shows
**NO PARSER** — write a rule with `source: "<Tag>"` (it is picked up without a
restart), or, if an existing rule fits a site-specific tag, map it in the
engine's `program_mapping` (`replicate.py` can suggest the rule from your
samples).
