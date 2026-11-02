#!/usr/bin/env python3
"""
TLSOC storage setup - data retention (ILM) and index templates
================================================================
Creates everything Elasticsearch needs so that logs are typed correctly and
expire on a schedule, BEFORE the first event is indexed. Safe to re-run: it
reconciles Elasticsearch with the values in .env, so changing a retention
value and running this script again is the supported way to change retention.

    ./elasticsearch/setup_storage.py                # apply .env settings
    ./elasticsearch/setup_storage.py --dry-run      # show what would change
    ./elasticsearch/setup_storage.py --no-existing  # do not touch old indices
    ./elasticsearch/setup_storage.py --reassign     # also move existing indices between tiers
    ./elasticsearch/setup_storage.py --confirm-shrink  # allow a shorter retention to delete data

What it creates (all names are prefixed `tlsoc-`):

  ILM policies
    tlsoc-logs              parsed logs        hot -> warm (compaction) -> delete
    tlsoc-logs-highvolume   noisy sources      same shape, shorter retention
    tlsoc-health            self-monitoring    delete after HEALTH_RETENTION_DAYS

  Component templates
    tlsoc-logs-mappings     field types, taken from the TLSOC Engine's template
    tlsoc-logs-settings     shards / replicas / refresh interval / ILM policy
    tlsoc-logs-hv-lifecycle ILM policy override for high-volume sources
    tlsoc-logs@custom       OPTIONAL, yours: extra mappings/settings, layered last.
                            Never created or changed by this script (see
                            docs/retention-and-storage.md)

  Index templates
    tlsoc-logs              fosstlsoc-logs-*             (priority 300)
    tlsoc-logs-hv-<source>  fosstlsoc-logs-<source>-*    (priority 400)
    tlsoc-threat-intel      tlsoc-threat-intel*          (+ creates the index)
    tlsoc-health            tlsoc-health-*               (from monitoring/)

Settings come from the stack .env (see .env.example, "Data retention"):
LOG_RETENTION_DAYS, WARM_AFTER_DAYS, HIGH_VOLUME_SOURCES,
HIGH_VOLUME_RETENTION_DAYS, HEALTH_RETENTION_DAYS, INDEX_SHARDS, INDEX_REPLICAS.

Standard library only.
"""

import argparse
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
from base64 import b64encode

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

LOGS_POLICY = "tlsoc-logs"
HV_POLICY = "tlsoc-logs-highvolume"
HEALTH_POLICY = "tlsoc-health"
CUSTOM_COMPONENT = "tlsoc-logs@custom"   # optional, operator-owned, never touched here
LOGS_PRIORITY = 300
HV_PRIORITY = 400
SEED_INDEX = "fosstlsoc-logs-_seed"

DEFAULTS = {
    "LOG_RETENTION_DAYS": "180",        # CERT-In: rolling 180 days
    "WARM_AFTER_DAYS": "7",
    "HIGH_VOLUME_SOURCES": "",
    "HIGH_VOLUME_RETENTION_DAYS": "30",
    "HEALTH_RETENTION_DAYS": "90",
    "INDEX_SHARDS": "1",
    "INDEX_REPLICAS": "0",              # single-node stack: replicas stay unassigned
    "ENGINE_DIR": "/etc/foss-soc-engine",
}


# --------------------------------------------------------------------------- #
# configuration
# --------------------------------------------------------------------------- #
def read_env_file(path):
    env = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return env


def load_config(args):
    env = dict(DEFAULTS)
    env.update(read_env_file(args.env_file))
    for k in list(DEFAULTS) + ["ELASTIC_PASSWORD", "HOST_IP"]:
        if os.environ.get(k):
            env[k] = os.environ[k]
    # blank values in .env fall back to the default
    for k, v in DEFAULTS.items():
        if not env.get(k, "").strip() and k != "HIGH_VOLUME_SOURCES":
            env[k] = v

    def days(name, minimum=1):
        try:
            value = int(env[name])
        except ValueError:
            die(f"{name} must be a whole number of days (got '{env[name]}')")
        if value < minimum:
            die(f"{name} must be at least {minimum}")
        return value

    cfg = {
        "retention": days("LOG_RETENTION_DAYS"),
        "warm_after": days("WARM_AFTER_DAYS"),
        "hv_retention": days("HIGH_VOLUME_RETENTION_DAYS"),
        "health_retention": days("HEALTH_RETENTION_DAYS"),
        "shards": days("INDEX_SHARDS"),
        "replicas": days("INDEX_REPLICAS", 0),
        "hv_sources": [],
        "password": env.get("ELASTIC_PASSWORD", ""),
        "host_ip": env.get("HOST_IP", ""),
        "engine_dir": env["ENGINE_DIR"],
    }
    for src in re.split(r"[,\s]+", env.get("HIGH_VOLUME_SOURCES", "").strip()):
        if not src:
            continue
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", src):
            die(f"HIGH_VOLUME_SOURCES: '{src}' is not a valid source name "
                "(lowercase letters, digits, _ and - only)")
        cfg["hv_sources"].append(src)
    return cfg


def die(msg):
    print(f"[storage] ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


# --------------------------------------------------------------------------- #
# Elasticsearch client (stdlib)
# --------------------------------------------------------------------------- #
class ES:
    def __init__(self, url, user, password, ca_cert, dry_run):
        self.url = url.rstrip("/")
        self.dry = dry_run
        self.auth = "Basic " + b64encode(f"{user}:{password}".encode()).decode()
        if ca_cert and os.path.exists(ca_cert):
            # The server certificate must chain to the stack's local CA. Host
            # names are not checked, so https://localhost works too.
            self.ctx = ssl.create_default_context(cafile=ca_cert)
            self.ctx.check_hostname = False
        else:
            self.ctx = ssl.create_default_context()
            self.ctx.check_hostname = False
            self.ctx.verify_mode = ssl.CERT_NONE

    def call(self, method, path, body=None, ok=(200,), mutating=None):
        mutating = (method != "GET") if mutating is None else mutating
        if self.dry and mutating:
            print(f"    (dry-run) {method} {path}")
            return {}
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method=method)
        req.add_header("Authorization", self.auth)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, context=self.ctx, timeout=60) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            if e.code in ok:
                return {}
            detail = e.read().decode(errors="replace")[:400]
            die(f"{method} {path} -> HTTP {e.code}: {detail}")
        except (urllib.error.URLError, OSError) as e:
            die(f"cannot reach Elasticsearch at {self.url}: {e}")

    def get(self, path, ok=(200,)):
        return self.call("GET", path, ok=ok + (404,)) or {}

    def put(self, path, body):
        return self.call("PUT", path, body)


# --------------------------------------------------------------------------- #
# policies and templates
# --------------------------------------------------------------------------- #
def logs_policy(retention, warm_after):
    """hot -> warm (set priority, merge to one segment, best compression) -> delete."""
    phases = {"hot": {"min_age": "0ms",
                      "actions": {"set_priority": {"priority": 100}}}}
    if 0 < warm_after < retention:
        phases["warm"] = {
            "min_age": f"{warm_after}d",
            "actions": {
                "set_priority": {"priority": 50},
                "forcemerge": {"max_num_segments": 1,
                               "index_codec": "best_compression"},
            },
        }
    phases["delete"] = {"min_age": f"{retention}d",
                        "actions": {"delete": {"delete_searchable_snapshot": True}}}
    return {"policy": {
        "_meta": {"description": "TLSOC parsed logs (managed by "
                                 "elasticsearch/setup_storage.py - edit .env, "
                                 "not this policy)"},
        "phases": phases}}


def health_policy(retention):
    return {"policy": {
        "_meta": {"description": "TLSOC self-monitoring data (managed by "
                                 "elasticsearch/setup_storage.py)"},
        "phases": {
            "hot": {"min_age": "0ms",
                    "actions": {"set_priority": {"priority": 100}}},
            "delete": {"min_age": f"{retention}d",
                       "actions": {"delete": {"delete_searchable_snapshot": True}}},
        }}}


def find_engine_template(explicit, engine_dir):
    candidates = []
    if explicit:
        candidates.append(("--engine-template", explicit))
    candidates.append(("installed engine",
                       os.path.join(engine_dir, "elasticsearch",
                                    "soc-index-template.json")))
    candidates.append(("bundled copy", os.path.join(HERE, "soc-index-template.json")))
    for label, path in candidates:
        if os.path.isfile(path):
            with open(path) as f:
                return label, path, json.load(f)
    die("no engine index template found (looked in: "
        + ", ".join(p for _, p in candidates) + ")")


def settings_component(cfg, policy):
    return {"template": {"settings": {"index": {
        "number_of_shards": cfg["shards"],
        "number_of_replicas": cfg["replicas"],
        "refresh_interval": "30s",
        "lifecycle": {"name": policy},
    }}},
        "_meta": {"managed_by": "elasticsearch/setup_storage.py"}}


STR_KEYWORD = {"type": "keyword", "ignore_above": 2048,
               "fields": {"keyword": {"type": "keyword", "ignore_above": 2048}}}


def threat_intel_template(cfg):
    return {
        "index_patterns": ["tlsoc-threat-intel*"],
        "priority": LOGS_PRIORITY,
        "template": {
            "settings": {"index": {"number_of_shards": 1,
                                   "number_of_replicas": cfg["replicas"]}},
            "mappings": {
                "dynamic_templates": [{"strings": {
                    "match_mapping_type": "string", "mapping": STR_KEYWORD}}],
                "properties": {
                    "@timestamp": {"type": "date"},
                    "abuse_score": {"type": "long"},
                    "to_ids": {"type": "boolean"},
                    # fields the dashboard aggregates on, mapped up front so its
                    # panels work before the first IOC arrives
                    "intel_source": STR_KEYWORD,
                    "ioc_type": STR_KEYWORD,
                    "ioc_value": STR_KEYWORD,
                    "pulse_name": STR_KEYWORD,
                    "tlsoc_type": STR_KEYWORD,
                    "tlsoc_category": STR_KEYWORD,
                },
            },
        },
        "_meta": {"managed_by": "elasticsearch/setup_storage.py"},
    }


def source_of(index):
    m = re.fullmatch(r"fosstlsoc-logs-(.+)-\d{4}\.\d{2}\.\d{2}", index)
    return m.group(1) if m else None


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="TLSOC retention (ILM) + templates setup")
    ap.add_argument("--env-file", default=os.environ.get(
        "ENV_FILE", os.path.join(REPO, ".env")))
    ap.add_argument("--es-url", default=os.environ.get("ES_URL"))
    ap.add_argument("--ca-cert", default=os.environ.get(
        "ES_CA_CERT", os.path.join(REPO, "certs", "ca", "ca.crt")))
    ap.add_argument("--engine-template", help="path to the engine's soc-index-template.json")
    ap.add_argument("--no-existing", action="store_true",
                    help="do not attach policies to indices that already exist")
    ap.add_argument("--reassign", action="store_true",
                    help="also move EXISTING indices between TLSOC policies when their "
                         "source changed tier (indices on a custom policy are never touched)")
    ap.add_argument("--confirm-shrink", action="store_true",
                    help="allow this run to cause existing data to be deleted "
                         "(a shorter retention, or old indices that have no policy yet)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = load_config(args)
    if not cfg["password"]:
        die(f"ELASTIC_PASSWORD not found in {args.env_file}")
    url = args.es_url or f"https://{cfg['host_ip'] or 'localhost'}:9200"
    es = ES(url, "elastic", cfg["password"], args.ca_cert, args.dry_run)

    info = es.call("GET", "/", mutating=False)
    print(f"[storage] Elasticsearch {info.get('version', {}).get('number', '?')} at {url}"
          + ("  (dry run)" if args.dry_run else ""))

    # ---- 0. never delete data by surprise
    risks = deletion_risks(es, cfg, args.reassign)
    if risks:
        print(f"[storage] WARNING: these settings would DELETE {len(risks)} existing "
              "index(es) within about 10 minutes (Elasticsearch checks lifecycles every 10 min):")
        for name, age, keep in risks[:10]:
            print(f"    {name}  is {age} days old, new retention keeps {keep} days")
        if len(risks) > 10:
            print(f"    ... and {len(risks) - 10} more")
        if args.dry_run:
            print("    (dry run: nothing deleted)")
        elif not args.confirm_shrink:
            die("refusing to continue. If this is intended, run again with "
                "--confirm-shrink; to keep the data, raise the retention in .env "
                "or snapshot it first (docs/retention-and-storage.md).")

    # ---- 1. ILM policies
    print("[storage] 1/5 ILM policies")
    es.put(f"/_ilm/policy/{LOGS_POLICY}", logs_policy(cfg["retention"], cfg["warm_after"]))
    print(f"    {LOGS_POLICY:24s} warm after {cfg['warm_after']}d, delete after {cfg['retention']}d")
    if cfg["hv_sources"]:
        es.put(f"/_ilm/policy/{HV_POLICY}",
               logs_policy(cfg["hv_retention"], min(cfg["warm_after"], max(cfg["hv_retention"] // 2, 1))))
        print(f"    {HV_POLICY:24s} delete after {cfg['hv_retention']}d "
              f"for: {', '.join(cfg['hv_sources'])}")
    es.put(f"/_ilm/policy/{HEALTH_POLICY}", health_policy(cfg["health_retention"]))
    print(f"    {HEALTH_POLICY:24s} delete after {cfg['health_retention']}d")

    # ---- 2. component templates
    label, path, engine_tpl = find_engine_template(args.engine_template, cfg["engine_dir"])
    print(f"[storage] 2/5 component templates (field types from the {label}: {path})")
    tpl_mappings = json.loads(json.dumps((engine_tpl.get("template") or {}).get("mappings", {})))
    # `service_name` is added by the Logstash pipeline (from the output file
    # name), not by the engine; the dashboard and collector aggregate on it.
    tpl_mappings.setdefault("properties", {})["service_name"] = {
        "type": "keyword", "ignore_above": 256,
        "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}}
    mappings = {"template": {
        "settings": (engine_tpl.get("template") or {}).get("settings", {}),
        "mappings": tpl_mappings},
        "_meta": {"managed_by": "elasticsearch/setup_storage.py",
                  "source": "foss-soc-engine soc-index-template.json"}}
    es.put("/_component_template/tlsoc-logs-mappings", mappings)
    es.put("/_component_template/tlsoc-logs-settings", settings_component(cfg, LOGS_POLICY))
    es.put("/_component_template/tlsoc-logs-hv-lifecycle",
           {"template": {"settings": {"index": {"lifecycle": {"name": HV_POLICY}}}},
            "_meta": {"managed_by": "elasticsearch/setup_storage.py"}})

    # ---- 3. index templates
    print("[storage] 3/5 index templates")
    es.put("/_index_template/tlsoc-logs", {
        "index_patterns": ["fosstlsoc-logs-*"], "priority": LOGS_PRIORITY,
        "composed_of": ["tlsoc-logs-mappings", "tlsoc-logs-settings", CUSTOM_COMPONENT],
        "ignore_missing_component_templates": [CUSTOM_COMPONENT],
        "_meta": {"managed_by": "elasticsearch/setup_storage.py"}})
    print(f"    tlsoc-logs               fosstlsoc-logs-*  -> {LOGS_POLICY}")
    wanted = {f"tlsoc-logs-hv-{s}" for s in cfg["hv_sources"]}
    for src in cfg["hv_sources"]:
        es.put(f"/_index_template/tlsoc-logs-hv-{src}", {
            "index_patterns": [f"fosstlsoc-logs-{src}-*"], "priority": HV_PRIORITY,
            "composed_of": ["tlsoc-logs-mappings", "tlsoc-logs-settings",
                            "tlsoc-logs-hv-lifecycle", CUSTOM_COMPONENT],
            "ignore_missing_component_templates": [CUSTOM_COMPONENT],
            "_meta": {"managed_by": "elasticsearch/setup_storage.py"}})
        print(f"    tlsoc-logs-hv-{src:11s} fosstlsoc-logs-{src}-*  -> {HV_POLICY}")
    # remove high-volume templates for sources no longer listed
    stale = [t["name"] for t in es.get("/_index_template/tlsoc-logs-hv-*").get("index_templates", [])
             if t["name"] not in wanted]
    for name in stale:
        es.call("DELETE", f"/_index_template/{name}")
        print(f"    removed stale template {name}")
    es.put("/_index_template/tlsoc-threat-intel", threat_intel_template(cfg))
    print("    tlsoc-threat-intel       tlsoc-threat-intel*")
    # The health collector's template is installed here (not only by the root-only
    # collector step) so it exists before the first health document is written:
    # an index created without it would get a replica that a single node can
    # never place, leaving the cluster yellow.
    health_file = os.path.join(REPO, "monitoring", "tlsoc-health-template.json")
    if os.path.isfile(health_file):
        with open(health_file) as f:
            health_tpl = json.load(f)
        idx = health_tpl.setdefault("template", {}).setdefault("settings", {})
        idx["number_of_shards"] = 1
        idx["number_of_replicas"] = cfg["replicas"]
        idx["index.lifecycle.name"] = HEALTH_POLICY
        es.put("/_index_template/tlsoc-health", health_tpl)
        print(f"    tlsoc-health             tlsoc-health-*  -> {HEALTH_POLICY}")

    # ---- 4. threat-intel index must exist so its dashboard panels work
    print("[storage] 4/5 base indices")
    # An empty index that carries the full field list. Kibana data views and
    # dashboard panels resolve fields against existing indices, so without it
    # every log panel errors until the first event is indexed. It holds no
    # documents, never expires (no ILM policy) and is invisible to reports.
    es.put("/_index_template/tlsoc-logs-seed", {
        "index_patterns": [SEED_INDEX], "priority": 500,
        "composed_of": ["tlsoc-logs-mappings"],
        "template": {"settings": {"index": {
            "number_of_shards": 1, "number_of_replicas": cfg["replicas"]}}},
        "_meta": {"managed_by": "elasticsearch/setup_storage.py"}})
    seed = es.get(f"/_cat/indices/{SEED_INDEX}?format=json")
    if isinstance(seed, list) and seed:
        print(f"    {SEED_INDEX} exists")
    else:
        es.put(f"/{SEED_INDEX}", {})
        print(f"    created {SEED_INDEX} (empty; lets dashboards resolve fields before data arrives)")
    exists = es.get("/_cat/indices/tlsoc-threat-intel?format=json")
    if isinstance(exists, list) and exists:
        # Templates only apply when an index is created, so add the dashboard
        # fields to an index that already exists. Adding a field is always
        # allowed; a field that is already mapped differently (an index that
        # holds data under the older dynamic mapping) is simply left as it is.
        props = threat_intel_template(cfg)["template"]["mappings"]["properties"]
        es.call("PUT", "/tlsoc-threat-intel/_mapping", {"properties": props}, ok=(200, 400))
        print("    tlsoc-threat-intel exists (field mappings ensured)")
    else:
        es.put("/tlsoc-threat-intel", {})
        print("    created tlsoc-threat-intel (empty)")

    # ---- 5. attach policies to indices that already exist
    print("[storage] 5/5 existing indices")
    if args.no_existing:
        print("    skipped (--no-existing)")
    else:
        attach_existing(es, cfg, args.reassign)
    print("[storage] done")


def policy_days(es, name):
    """Days after which a TLSOC policy deletes an index, or None if it does not exist."""
    pol = es.get(f"/_ilm/policy/{name}").get(name, {}).get("policy", {})
    age = (pol.get("phases", {}).get("delete") or {}).get("min_age", "")
    m = re.fullmatch(r"(\d+)d", age)
    return int(m.group(1)) if m else None


def deletion_risks(es, cfg, reassign):
    """Indices that THIS run would cause to be deleted although they are still
    kept today: a shortened retention, or an old index that has no policy yet
    and is about to get one. Returns [(index, age_days, will_keep_days)]."""
    import time
    rows = es.get("/_cat/indices/fosstlsoc-logs-*,tlsoc-health-*?format=json&h=index,creation.date")
    names = {r["index"]: int(r["creation.date"]) for r in rows
             if isinstance(rows, list) and r["index"] != SEED_INDEX}
    if not names:
        return []
    lifecycle = es.get("/" + ",".join(names) + "/_settings/index.lifecycle.name")
    new_days = {LOGS_POLICY: cfg["retention"], HEALTH_POLICY: cfg["health_retention"]}
    if cfg["hv_sources"]:
        new_days[HV_POLICY] = cfg["hv_retention"]
    old_days = {n: policy_days(es, n) for n in (LOGS_POLICY, HV_POLICY, HEALTH_POLICY)}
    now_ms = time.time() * 1000
    risks = []
    for name, created in names.items():
        age = (now_ms - created) / 86400000.0
        cur = (((lifecycle.get(name) or {}).get("settings", {}).get("index", {}))
               .get("lifecycle") or {}).get("name")
        if cur and cur not in new_days and cur not in old_days:
            continue                                    # custom policy: not ours to judge
        want = desired_policy(name, cfg)
        will_have = want if (not cur or (reassign and cur in old_days)) else cur
        after = new_days.get(will_have)
        before = old_days.get(cur) if cur else None     # None = kept forever today
        if after is not None and age > after and (before is None or age <= before):
            risks.append((name, int(age), after))
    return sorted(risks)


def desired_policy(name, cfg):
    if name.startswith("tlsoc-health-"):
        return HEALTH_POLICY
    return HV_POLICY if source_of(name) in cfg["hv_sources"] else LOGS_POLICY


def attach_existing(es, cfg, reassign=False):
    """Give policy-less indices a policy. An index that already has one is left
    alone, unless --reassign is given AND its policy is one of TLSOC's own (an
    operator's custom policy is never overridden)."""
    rows = es.get("/_cat/indices/fosstlsoc-logs-*,tlsoc-health-*?format=json&h=index,rep")
    names = [r["index"] for r in rows if r["index"] != SEED_INDEX] if isinstance(rows, list) else []
    if not names:
        print("    none yet")
        return
    lifecycle = es.get("/" + ",".join(names) + "/_settings/index.lifecycle.name,index.number_of_replicas")
    ours = {LOGS_POLICY, HV_POLICY, HEALTH_POLICY}
    attached = moved = unchanged = replicas_fixed = 0
    for name in names:
        idx = (lifecycle.get(name) or {}).get("settings", {}).get("index", {})
        current = (idx.get("lifecycle") or {}).get("name")
        want = desired_policy(name, cfg)
        body = {}
        if not current:
            body["index.lifecycle.name"] = want
            attached += 1
        elif reassign and current in ours and current != want:
            body["index.lifecycle.name"] = want
            moved += 1
        else:
            unchanged += 1
        if cfg["replicas"] == 0 and str(idx.get("number_of_replicas", "0")) != "0":
            body["index.number_of_replicas"] = 0
            replicas_fixed += 1
        if body:
            es.put(f"/{name}/_settings", body)
    print(f"    {attached} attached to a policy, {moved} moved to another tier, "
          f"{unchanged} left as they were"
          + (f", {replicas_fixed} set to 0 replicas" if replicas_fixed else ""))


if __name__ == "__main__":
    main()
