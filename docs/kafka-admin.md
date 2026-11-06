# Kafka Admin Cheat Sheet

Day-to-day Kafka topic operations on the TLSOC server. All commands run from the
deployment directory:

```bash
cd /opt/TLSOCDockerDeploy/
```

## The TLSOC topics

Each log source has its own topic, `tlsoc.logs.<source>`
([Log sources and Kafka topics](sources-and-topics.md)). None is created in
advance: a source's topic is created automatically on its first line, and a
cron job gives it the partitions/retention in
[`kafka/topics.conf`](../kafka/topics.conf). Manage them with:

```bash
sudo ./kafka/setup-topics.sh                  # apply topics.conf to existing topics (safe to repeat)
sudo ./kafka/setup-topics.sh --list           # TLSOC topics, partitions, retention
sudo ./kafka/setup-topics.sh --dry-run        # show what would change
sudo ./kafka/setup-topics.sh --remove-unused  # delete TLSOC topics that never held a message
```

Per-source flow, lag and parser at a glance — on the engine host:

```bash
cd /etc/foss-soc-engine && python3 sources.py
```

## List all topics

```bash
docker exec -it kafka /opt/kafka/bin/kafka-topics.sh \
  --bootstrap-server kafka:9092 --list
```

## Describe a topic

Shows partition count, leader, and replication — useful when sizing the engine's
worker pool (partitions cap parallelism):

```bash
docker exec -it kafka /opt/kafka/bin/kafka-topics.sh \
  --bootstrap-server kafka:9092 --describe --topic <topic>
```

## Live-watch a topic

```bash
docker exec -it kafka /opt/kafka/bin/kafka-console-consumer.sh \
  --bootstrap-server kafka:9092 --topic <topic>
```

## Read a topic from the beginning

```bash
docker exec -it kafka /opt/kafka/bin/kafka-console-consumer.sh \
  --bootstrap-server kafka:9092 --topic <topic> --from-beginning
```

## Approximate message count

```bash
docker exec -it kafka /opt/kafka/bin/kafka-get-offsets.sh \
  --bootstrap-server kafka:9092 --topic <topic>
```

## Consumer lag (how far behind the engine is, per topic and partition)

```bash
docker exec -it kafka /opt/kafka/bin/kafka-consumer-groups.sh \
  --bootstrap-server kafka:9092 --describe --group soc-parser-group
```

## Add partitions to a topic

One partition is consumed by at most one engine worker, so a busy source needs
several partitions before several workers can share it
(see [TLSOC Engine — Deployment & Scaling](https://github.com/sankettaware16/foss-soc-engine/blob/main/docs/deployment.md)).
Preferably raise the number in `kafka/topics.conf` (the cron job applies it
within 5 minutes, or run `sudo ./kafka/setup-topics.sh`), so it is recorded; or
directly:

```bash
docker exec -it kafka /opt/kafka/bin/kafka-topics.sh \
  --bootstrap-server kafka:9092 --alter --topic tlsoc.logs.squid --partitions 12
```

> Partitions can only be increased, never decreased. Keep **one** partition for
> sources whose rule joins several lines of one transaction (postfix): their
> lines must stay in order.
