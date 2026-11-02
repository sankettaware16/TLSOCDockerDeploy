#!/usr/bin/env python3
"""
TLSOC Health Collector
======================
Collects SIEM pipeline health and indexes it into Elasticsearch
(`tlsoc-health-YYYY.MM`) so the "TLSOC - SOC Overview" Kibana dashboard can
show service uptime, pipeline throughput and log-source freshness.

Components checked (one document per component per run):

  elasticsearch   cluster health, heap %, disk %, docs, indexing rate
  kibana          /api/status overall level
  logstash        container state + node stats (events in/out rates)
  kafka           container state + consumer-group lag (soc-parser-group)
  parser-engine   foss-soc-engine heartbeat + stats.json (EPS, match rate)
  host            load / memory / disk of the SIEM host
  overall         worst status across core components
  source:<name>   per log source: seconds since last event, 5m/24h volume
                  (event.dataset: tlsoc.source_health)

Runs on the SIEM host via cron (see install-health-collector.sh).
`--remote` mode skips docker/kafka/parser/host checks so it can also run from
any workstation that only reaches ES 9200 / Kibana 5601.

Stdlib only - no pip dependencies.
"""

import argparse
import glob
import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

DOCKER_CONTAINERS = ["elasticsearch", "kibana", "logstash", "kafka"]
KAFKA_CONSUMER_GROUP = "soc-parser-group"
ENGINE_LOG_DIR_CANDIDATES = [
    "/etc/foss-soc-engine/logs",
    "/opt/foss-soc-engine/logs",
    "/opt/tlsoc/foss-soc-engine/logs",
    os.path.expanduser("~/foss-soc-engine/logs"),
]
# Source freshness thresholds (seconds since last event)
SOURCE_ACTIVE_SEC = 600      # < 10 min  -> active
SOURCE_STALE_SEC = 3600      # < 60 min  -> stale, beyond -> dead

UP, DEGRADED, DOWN = 2, 1, 0
STATUS_WORD = {2: "up", 1: "degraded", 0: "down"}

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def http_json(url, user=None, password=None, timeout=10, method="GET", body=None,
              content_type="application/json"):
    req = urllib.request.Request(url, method=method)
    if body is not None:
        req.data = body.encode() if isinstance(body, str) else body
        req.add_header("Content-Type", content_type)
    if user:
        import base64
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
        return json.loads(r.read().decode())


def read_env_file(path):
    vals = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    vals[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return vals


def run_cmd(cmd, timeout=40):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        return 127, "", str(e)


def iso_age_seconds(ts):
    """Age in seconds of an ISO timestamp (engine stats use isoformat)."""
    if not ts:
        return None
    try:
        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - t).total_seconds())
    except ValueError:
        return None


class Collector:
    def __init__(self, args):
        self.args = args
        env = read_env_file(args.env_file)
        self.es_user = args.es_user
        self.es_pass = args.es_password or env.get("ELASTIC_PASSWORD") or ""
        self.es_url = args.es_url.rstrip("/")
        self.kibana_url = args.kibana_url.rstrip("/")
        self.docs = []
        self.state = self._load_state()
        self.new_state = {"ts": time.time()}

    # ---------------- state (for rate-from-counter deltas) ----------------
    def _load_state(self):
        try:
            with open(self.args.state_file) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save_state(self):
        try:
            os.makedirs(os.path.dirname(self.args.state_file), exist_ok=True)
            with open(self.args.state_file, "w") as f:
                json.dump(self.new_state, f)
        except OSError as e:
            print(f"[warn] cannot save state file: {e}", file=sys.stderr)

    def _rate(self, key, current_total):
        """docs/sec computed from the previous run's counter, or None."""
        prev = self.state.get(key)
        prev_ts = self.state.get("ts")
        self.new_state[key] = current_total
        if prev is None or prev_ts is None or current_total < prev:
            return None
        dt = time.time() - prev_ts
        if dt <= 0:
            return None
        return round((current_total - prev) / dt, 2)

    # ---------------- doc helpers ----------------
    def add(self, component, code, details="", dataset="tlsoc.health", **extra):
        doc = {
            "@timestamp": now_iso(),
            "event": {"dataset": dataset},
            "component": component,
            "status": extra.pop("status_word", None) or STATUS_WORD[code],
            "status_code": code,
            "details": details[:900],
            "collector": {"mode": "remote" if self.args.remote else "server"},
        }
        doc.update(extra)
        self.docs.append(doc)
        return doc

    # ---------------- checks ----------------
    def check_elasticsearch(self):
        try:
            h = http_json(f"{self.es_url}/_cluster/health", self.es_user, self.es_pass)
            nodes = http_json(f"{self.es_url}/_nodes/stats/jvm,fs,os,indices",
                              self.es_user, self.es_pass)
            heap = disk_used_pct = cpu = None
            docs_total = store_bytes = index_total = 0
            for n in nodes.get("nodes", {}).values():
                heap = n.get("jvm", {}).get("mem", {}).get("heap_used_percent", heap)
                cpu = n.get("os", {}).get("cpu", {}).get("percent", cpu)
                fs = n.get("fs", {}).get("total", {})
                tot, free = fs.get("total_in_bytes"), fs.get("free_in_bytes")
                if tot:
                    disk_used_pct = round(100.0 * (tot - free) / tot, 1)
                idx = n.get("indices", {})
                docs_total += idx.get("docs", {}).get("count", 0)
                store_bytes += idx.get("store", {}).get("size_in_bytes", 0)
                index_total += idx.get("indexing", {}).get("index_total", 0)
            rate = self._rate("es_index_total", index_total)
            status = {"green": UP, "yellow": DEGRADED, "red": DOWN}.get(
                h.get("status"), DOWN)
            gb = round(store_bytes / 1024 ** 3, 1)
            self.add("elasticsearch", status,
                     f"cluster {h.get('status')} | {h.get('active_shards')} shards | "
                     f"{docs_total:,} docs | {gb} GB | heap {heap}% | disk {disk_used_pct}%",
                     es={"cluster_status": h.get("status"),
                         "active_shards": h.get("active_shards"),
                         "heap_percent": heap, "cpu_percent": cpu,
                         "disk_used_percent": disk_used_pct,
                         "docs_total": docs_total, "store_bytes": store_bytes,
                         "indexing_rate": rate})
        except Exception as e:
            self.add("elasticsearch", DOWN, f"unreachable: {e}")

    def check_kibana(self):
        try:
            s = http_json(f"{self.kibana_url}/api/status", self.es_user, self.es_pass)
            level = s.get("status", {}).get("overall", {}).get("level", "unavailable")
            code = {"available": UP, "degraded": DEGRADED}.get(level, DOWN)
            ver = s.get("version", {}).get("number", "")
            self.add("kibana", code, f"{level} | v{ver}",
                     kibana={"status": level})
        except Exception as e:
            self.add("kibana", DOWN, f"unreachable: {e}")

    # ---- docker helpers (server mode) ----
    def docker_inspect(self):
        rc, out, err = run_cmd(["docker", "inspect"] + DOCKER_CONTAINERS)
        if rc != 0:
            print(f"[warn] docker inspect failed: {err.strip()[:200]}", file=sys.stderr)
            return {}
        info = {}
        try:
            for c in json.loads(out):
                name = c.get("Name", "").lstrip("/")
                st = c.get("State", {})
                started = st.get("StartedAt", "")
                uptime = iso_age_seconds(re.sub(r"\.\d+", "", started)) or 0
                info[name] = {
                    "state": st.get("Status", "unknown"),
                    "health": (st.get("Health") or {}).get("Status", ""),
                    "restart_count": c.get("RestartCount", 0),
                    "started_at": started,
                    "uptime_seconds": int(uptime),
                    "ip": self._container_ip(c),
                }
        except ValueError:
            pass
        return info

    @staticmethod
    def _container_ip(inspect_obj):
        nets = inspect_obj.get("NetworkSettings", {}).get("Networks", {})
        for net in nets.values():
            if net.get("IPAddress"):
                return net["IPAddress"]
        return None

    @staticmethod
    def _human_uptime(sec):
        d, rem = divmod(int(sec), 86400)
        h, rem = divmod(rem, 3600)
        m = rem // 60
        return (f"{d}d {h}h" if d else f"{h}h {m}m")

    def container_doc(self, name, info, extra_detail="", **extra):
        c = info.get(name)
        if not c:
            self.add(name, DOWN, "container not found (docker inspect failed?)")
            return None
        code = UP if c["state"] == "running" else DOWN
        if c["health"] and c["health"] not in ("healthy", ""):
            code = min(code, DEGRADED)
        detail = (f"{c['state']} | up {self._human_uptime(c['uptime_seconds'])} | "
                  f"restarts {c['restart_count']}")
        if extra_detail:
            detail += " | " + extra_detail
        self.add(name, code, detail,
                 container={"state": c["state"], "health": c["health"],
                            "restart_count": c["restart_count"],
                            "uptime_seconds": c["uptime_seconds"]},
                 **extra)
        return c

    def _logstash_node_stats(self, container_ip):
        """Logstash API via container IP; falls back to docker exec curl
        (the API binds to 127.0.0.1 inside the container by default)."""
        if container_ip:
            try:
                return http_json(f"http://{container_ip}:9600/_node/stats/events",
                                 timeout=8)
            except Exception:
                pass
        rc, out, _ = run_cmd(["docker", "exec", "logstash", "curl", "-s",
                              "http://127.0.0.1:9600/_node/stats/events"],
                             timeout=15)
        if rc == 0 and out.strip():
            return json.loads(out)
        raise RuntimeError("logstash API unreachable (direct + docker exec)")

    def check_logstash(self, dinfo):
        c = dinfo.get("logstash")
        stats = {}
        detail = ""
        if c and c["state"] == "running":
            try:
                s = self._logstash_node_stats(c.get("ip"))
                ev = s.get("events", {})
                in_rate = self._rate("ls_events_in", ev.get("in", 0))
                out_rate = self._rate("ls_events_out", ev.get("out", 0))
                stats = {"events_in": ev.get("in", 0), "events_out": ev.get("out", 0),
                         "events_filtered": ev.get("filtered", 0),
                         "in_rate": in_rate, "out_rate": out_rate}
                detail = (f"in {in_rate if in_rate is not None else '?'}/s, "
                          f"out {out_rate if out_rate is not None else '?'}/s")
            except Exception as e:
                detail = f"api error: {e}"
        self.container_doc("logstash", dinfo, detail,
                           **({"logstash": stats} if stats else {}))

    def kafka_group(self):
        """Consumer group to report lag for: --kafka-group / TLSOC_KAFKA_GROUP,
        else `kafka.group_id` from the engine's config.yaml, else the default."""
        if self.args.kafka_group:
            return self.args.kafka_group
        log_dir = self.engine_logs_dir()
        if log_dir:
            cfg = os.path.join(os.path.dirname(log_dir.rstrip("/")), "config.yaml")
            try:
                with open(cfg) as f:
                    m = re.search(r'^\s*group_id:\s*["\']?([^"\'#\s]+)', f.read(), re.M)
                if m:
                    return m.group(1)
            except OSError:
                pass
        return KAFKA_CONSUMER_GROUP

    def check_kafka(self, dinfo):
        group = self.kafka_group()
        c = dinfo.get("kafka")
        extra = {}
        detail = ""
        if c and c["state"] == "running":
            rc, out, err = run_cmd(
                ["docker", "exec", "kafka",
                 "/opt/kafka/bin/kafka-consumer-groups.sh",
                 "--bootstrap-server", "localhost:9092",
                 "--describe", "--group", group], timeout=45)
            if rc == 0 and out.strip():
                lag_total, partitions = 0, 0
                for line in out.splitlines():
                    cols = line.split()
                    # GROUP TOPIC PARTITION CURRENT-OFFSET LOG-END-OFFSET LAG ...
                    if len(cols) >= 6 and cols[0] == group:
                        partitions += 1
                        try:
                            lag_total += int(cols[5])
                        except ValueError:
                            pass
                extra["kafka"] = {"consumer_group": group,
                                  "total_lag": lag_total, "partitions": partitions}
                detail = f"lag {lag_total:,} ({partitions} partitions)"
            else:
                detail = f"lag check failed: {(err or out).strip()[:120]}"
        self.container_doc("kafka", dinfo, detail, **extra)

    @staticmethod
    def _engine_dir_from_systemd():
        """foss-soc-engine installs itself as the 'foss-soc' systemd service
        with WorkingDirectory = its checkout dir (see setup_service.sh)."""
        for unit in ("foss-soc", "foss-soc-engine"):
            rc, out, _ = run_cmd(["systemctl", "show", "-p", "WorkingDirectory",
                                  "--value", unit], timeout=10)
            wd = out.strip()
            if rc == 0 and wd and os.path.isdir(os.path.join(wd, "logs")):
                return os.path.join(wd, "logs")
        return None

    def engine_logs_dir(self):
        """The foss-soc-engine logs directory, or None if no engine is installed."""
        if hasattr(self, "_engine_logs"):
            return self._engine_logs
        log_dir = self.args.engine_logs or self._engine_dir_from_systemd()
        if not log_dir:
            candidates = ENGINE_LOG_DIR_CANDIDATES + \
                sorted(glob.glob("/opt/*/logs")) + \
                sorted(glob.glob("/home/*/foss-soc-engine/logs"))
            for cand in candidates:
                if os.path.isdir(cand) and (
                        os.path.exists(os.path.join(cand, "engine.pid")) or
                        glob.glob(os.path.join(cand, "stats*.json"))):
                    log_dir = cand
                    break
        self._engine_logs = log_dir if log_dir and os.path.isdir(log_dir) else None
        return self._engine_logs

    def check_parser_engine(self):
        log_dir = self.engine_logs_dir()
        if not log_dir:
            # Not an outage: on a fresh stack the engine is installed after the
            # core stack (README step 3). Show it, but keep it out of `overall`.
            self.add("parser-engine", DEGRADED,
                     "not installed yet - install foss-soc-engine to parse logs "
                     "(set --engine-logs if it is installed elsewhere)",
                     status_word="not-installed", optional=True)
            return
        files = sorted(glob.glob(os.path.join(log_dir, "stats.w*.json"))) or \
            [os.path.join(log_dir, "stats.json")]
        workers, eps, processed, errors = 0, 0.0, 0, 0
        parsed = no_match = rule_err = 0
        newest_age = None
        for path in files:
            try:
                with open(path) as f:
                    s = json.load(f)
            except (OSError, ValueError):
                continue
            age = iso_age_seconds(s.get("timestamp"))
            if age is not None and (newest_age is None or age < newest_age):
                newest_age = age
            if age is not None and age > 120:
                continue  # stale worker file from a previous run
            workers += 1
            eps += s.get("eps", 0) or 0
            processed += s.get("total_processed", 0) or 0
            errors += s.get("total_errors", 0) or 0
            for st in (s.get("parser_stats") or {}).values():
                parsed += st.get("parsed_messages", 0)
                no_match += st.get("no_match", 0)
                rule_err += st.get("errors", 0)
        attempted = parsed + no_match + rule_err
        match_rate = round(100.0 * parsed / attempted, 1) if attempted else None
        if workers == 0:
            self.add("parser-engine", DOWN,
                     f"no fresh stats in {log_dir} (engine stopped?)",
                     parser={"heartbeat_age_sec": newest_age})
            return
        code = UP if (newest_age is not None and newest_age < 60) else DEGRADED
        self.add("parser-engine", code,
                 f"{workers} worker(s) | {round(eps,1)} EPS | "
                 f"match {match_rate}% | {processed:,} processed",
                 parser={"eps": round(eps, 2), "match_rate": match_rate,
                         "parsed_total": parsed, "no_match_total": no_match,
                         "errors_total": errors, "workers": workers,
                         "heartbeat_age_sec": newest_age})

    def check_host(self):
        try:
            load1 = os.getloadavg()[0]
            cores = os.cpu_count() or 1
            mem = {}
            with open("/proc/meminfo") as f:
                for line in f:
                    k, v = line.split(":", 1)
                    mem[k] = int(v.strip().split()[0])
            mem_pct = round(100.0 * (1 - mem["MemAvailable"] / mem["MemTotal"]), 1)
            st = os.statvfs("/")
            disk_pct = round(100.0 * (1 - st.f_bavail / st.f_blocks), 1)
            code = UP
            if mem_pct > 90 or disk_pct > 85 or load1 > cores * 2:
                code = DEGRADED
            self.add("host", code,
                     f"load {load1:.2f}/{cores} cores | mem {mem_pct}% | disk {disk_pct}%",
                     host={"load1": round(load1, 2), "mem_percent": mem_pct,
                           "disk_percent": disk_pct, "cores": cores})
        except OSError as e:
            self.add("host", DEGRADED, f"host stats error: {e}")

    def check_sources(self):
        """Freshness of every log source seen in the last 7 days."""
        body = json.dumps({
            "size": 0,
            "query": {"range": {"@timestamp": {"gte": "now-7d"}}},
            "aggs": {"src": {
                "terms": {"field": "service_name.keyword", "size": 100},
                "aggs": {
                    "last_event": {"max": {"field": "@timestamp"}},
                    "last24h": {"filter": {"range": {"@timestamp": {"gte": "now-24h"}}}},
                    "last5m": {"filter": {"range": {"@timestamp": {"gte": "now-5m"}}}},
                }}}})
        try:
            r = http_json(f"{self.es_url}/fosstlsoc-logs-*/_search",
                          self.es_user, self.es_pass, body=body, timeout=30)
        except Exception as e:
            print(f"[warn] source freshness query failed: {e}", file=sys.stderr)
            return []
        rows = []
        for b in r.get("aggregations", {}).get("src", {}).get("buckets", []):
            name = b["key"]
            last_ms = b["last_event"].get("value")
            lag = (time.time() - last_ms / 1000.0) if last_ms else None
            if lag is None or lag > SOURCE_STALE_SEC:
                word, code = "dead", DOWN
            elif lag < -120:
                # newest event is in the FUTURE: almost always a timezone
                # bug in the parser rule (local time stored as UTC)
                word, code = "clock-skew", DEGRADED
            elif lag > SOURCE_ACTIVE_SEC:
                word, code = "stale", DEGRADED
            else:
                word, code = "active", UP
            if word == "clock-skew":
                detail = (f"timestamps {int(-lag)}s in the FUTURE - check tz "
                          f"in parser rule | {b['last24h']['doc_count']:,} "
                          f"events (24h)")
            elif lag is not None:
                detail = (f"last event {int(lag)}s ago | "
                          f"{b['last24h']['doc_count']:,} events (24h)")
            else:
                detail = "no events"
            self.add(f"source:{name}", code, detail,
                     dataset="tlsoc.source_health", status_word=word,
                     log_source={
                         "name": name,
                         "lag_seconds": int(lag) if lag is not None else None,
                         "last_event": b["last_event"].get("value_as_string"),
                         "events_5m": b["last5m"]["doc_count"],
                         "events_24h": b["last24h"]["doc_count"],
                     })
            rows.append((name, word, code))
        return rows

    # ---------------- overall + output ----------------
    def overall(self):
        core = [d for d in self.docs if d["event"]["dataset"] == "tlsoc.health"
                and d["component"] != "host" and not d.get("optional")]
        srcs = [d for d in self.docs if d["event"]["dataset"] == "tlsoc.source_health"]
        if not core:
            return
        worst_core = min(d["status_code"] for d in core)
        code = worst_core
        # A dead/stale source degrades the SIEM but doesn't mark it down.
        if code == UP and srcs and min(d["status_code"] for d in srcs) < UP:
            code = DEGRADED
        bad = [d["component"] for d in core + srcs if d["status_code"] < UP]
        detail = "all components up" if not bad else "issues: " + ", ".join(bad[:8])
        self.add("overall", code, detail)

    def bulk_index(self):
        index = "tlsoc-health-" + datetime.now(timezone.utc).strftime("%Y.%m")
        lines = []
        for d in self.docs:
            lines.append(json.dumps({"index": {"_index": index}}))
            lines.append(json.dumps(d))
        body = "\n".join(lines) + "\n"
        r = http_json(f"{self.es_url}/_bulk", self.es_user, self.es_pass,
                      method="POST", body=body, content_type="application/x-ndjson",
                      timeout=30)
        if r.get("errors"):
            first = next((i for i in r["items"] if i["index"].get("error")), {})
            print(f"[error] bulk had errors: {json.dumps(first)[:400]}", file=sys.stderr)
            return False
        return True

    def run(self):
        self.check_elasticsearch()
        self.check_kibana()
        if not self.args.remote:
            dinfo = self.docker_inspect()
            self.check_logstash(dinfo)
            self.check_kafka(dinfo)
            self.check_parser_engine()
            self.check_host()
        self.check_sources()
        self.overall()

        for d in self.docs:
            print(f"  {d['component']:<22} {d['status']:<9} {d['details']}")

        if self.args.dry_run:
            print("[dry-run] not indexing", len(self.docs), "docs")
        else:
            ok = self.bulk_index()
            print(f"[{'ok' if ok else 'FAIL'}] indexed {len(self.docs)} docs")
        self._save_state()


def main():
    ap = argparse.ArgumentParser(description="TLSOC SIEM health collector")
    ap.add_argument("--es-url", default=os.environ.get("TLSOC_ES_URL",
                    "https://localhost:9200"))
    ap.add_argument("--kibana-url", default=os.environ.get("TLSOC_KIBANA_URL",
                    "https://localhost:5601"))
    ap.add_argument("--es-user", default=os.environ.get("TLSOC_ES_USER", "elastic"))
    ap.add_argument("--es-password", default=os.environ.get("ELASTIC_PASSWORD"))
    ap.add_argument("--env-file", default=os.environ.get("TLSOC_ENV_FILE",
                    "/opt/TLSOCDockerDeploy/.env"),
                    help=".env file to read ELASTIC_PASSWORD from")
    ap.add_argument("--engine-logs", default=os.environ.get("TLSOC_ENGINE_LOGS"),
                    help="foss-soc-engine logs dir (auto-detected if omitted)")
    ap.add_argument("--kafka-group", default=os.environ.get("TLSOC_KAFKA_GROUP"),
                    help="engine consumer group to report lag for "
                         "(default: group_id from the engine's config.yaml)")
    ap.add_argument("--state-file", default=os.environ.get("TLSOC_STATE_FILE",
                    "/var/lib/tlsoc-health/state.json"))
    ap.add_argument("--remote", action="store_true",
                    help="only run checks that work over HTTP (no docker/ssh)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    Collector(args).run()


if __name__ == "__main__":
    main()
