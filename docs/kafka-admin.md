# Kafka Admin Cheat Sheet

Day-to-day Kafka topic operations on the TLSOC server. All commands run from the
deployment directory:

```bash
cd /opt/TLSOCDockerDeploy/
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
docker exec -it kafka /opt/kafka/bin/kafka-run-class.sh kafka.tools.GetOffsetShell \
  --broker-list kafka:9092 --topic <topic>
```

## Add partitions to a topic

One partition is consumed by at most one engine worker — provision at least as
many partitions as total workers
(see [TLSOC Engine — Deployment & Scaling](https://github.com/sankettaware16/foss-soc-engine/blob/main/docs/deployment.md)):

```bash
docker exec -it kafka /opt/kafka/bin/kafka-topics.sh \
  --bootstrap-server kafka:9092 --alter --topic <topic> --partitions 12
```

> Partitions can only be increased, never decreased. Increasing them changes
> key→partition assignment for new messages; lines from one source still stay
> together (same key), so stateful parsing is unaffected going forward.
