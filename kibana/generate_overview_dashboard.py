#!/usr/bin/env python3
"""
Generates kibana/saved_objects/tlsoc_overview_dashboard.ndjson
==============================================================
"TLSOC - SOC Overview" landing dashboard for Kibana 8.19.x.

Panels are driven by four data views (created by the same file):

  fosstlsoc-logs-*                      parsed logs (foss-soc-engine output)
  tlsoc-health-*                        health collector (monitoring/)
  .alerts-security.alerts-<space>       detection-engine alerts (--space)
  tlsoc-threat-intel*                   threat intel collectors

Import:  Kibana > Stack Management > Saved Objects > Import
   or:   curl -sk -u elastic:$PASS -X POST \
            "https://<ip>:5601/api/saved_objects/_import?overwrite=true" \
            -H "kbn-xsrf: true" --form file=@tlsoc_overview_dashboard.ndjson
         (custom space: regenerate with --space <id> and prefix /s/<id>)

Re-run this script after editing panels, then re-import.
"""

import argparse
import json
import os
import uuid

ARGS = argparse.ArgumentParser(description=__doc__)
ARGS.add_argument("--space", default="default",
                  help="Kibana space id the dashboard will live in; sets the "
                       "detection-alerts index the alert panels read "
                       "(.alerts-security.alerts-<space>). Default: default")
ARGS.add_argument("--out", default=os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "saved_objects", "tlsoc_overview_dashboard.ndjson"))
ARGS = ARGS.parse_args()
OUT = ARGS.out

# Fixed IDs so re-imports update in place instead of duplicating.
DV_LOGS = "tlsoc-logs-all-dv"
DV_HEALTH = "tlsoc-health-dv"
DV_ALERTS = "tlsoc-alerts-dv"
DV_INTEL = "tlsoc-intel-dv"
DASHBOARD_ID = "tlsoc-soc-overview"

GREEN, YELLOW, RED, BLUE = "#209280", "#D6BF57", "#E7664C", "#6092C0"

# Panels on these data views ignore the dashboard-level query/filters and the
# controls: they are status panels (health strip, alerts, intel) that should
# always show the full picture. Controls therefore filter the LOG panels.
# (service_name does not exist in the alert docs, so a source selection would
# otherwise just blank the alert panels.)
IGNORE_FILTER_DVS = {DV_HEALTH, DV_ALERTS, DV_INTEL}

# Dashboard controls: options-list dropdowns over the logs data view.
CONTROLS = [
    {"field": "service_name.keyword", "title": "Log source"},
    {"field": "source.geo.country_name", "title": "Source country"},
    {"field": "url.domain.keyword", "title": "Domain"},
]


def uid():
    return str(uuid.uuid4())


# --------------------------------------------------------------------------
# column builders (Lens formBased datasource)
# --------------------------------------------------------------------------
def col_count(label="Count", compact=True, decimals=0):
    return {
        "label": label, "dataType": "number", "operationType": "count",
        "isBucketed": False, "scale": "ratio", "sourceField": "___records___",
        "customLabel": True,
        "params": {"emptyAsNull": True,
                   "format": {"id": "number",
                              "params": {"decimals": decimals, "compact": compact}}},
    }


def col_unique(field, label, compact=False):
    return {
        "label": label, "dataType": "number", "operationType": "unique_count",
        "isBucketed": False, "scale": "ratio", "sourceField": field,
        "customLabel": True,
        "params": {"emptyAsNull": True,
                   "format": {"id": "number",
                              "params": {"decimals": 0, "compact": compact}}},
    }


def col_last_num(field, label, decimals=0, suffix="", compact=False):
    p = {"sortField": "@timestamp", "showArrayValues": False,
         "format": {"id": "number", "params": {"decimals": decimals,
                                               "compact": compact}}}
    if suffix:
        p["format"]["params"]["suffix"] = suffix
    return {
        "label": label, "dataType": "number", "operationType": "last_value",
        "isBucketed": False, "scale": "ratio", "sourceField": field,
        "customLabel": True,
        "filter": {"query": f'"{field}": *', "language": "kuery"},
        "params": p,
    }


def col_last_str(field, label):
    return {
        "label": label, "dataType": "string", "operationType": "last_value",
        "isBucketed": False, "scale": "ordinal", "sourceField": field,
        "customLabel": True,
        "filter": {"query": f'"{field}": *', "language": "kuery"},
        "params": {"sortField": "@timestamp", "showArrayValues": False},
    }


def col_date_hist():
    return {
        "label": "@timestamp", "dataType": "date",
        "operationType": "date_histogram", "sourceField": "@timestamp",
        "isBucketed": True, "scale": "interval",
        "params": {"interval": "auto", "includeEmptyRows": True,
                   "dropPartials": False},
    }


def col_terms(field, order_by_col=None, size=8, label=None, other=False,
              exclude=None, exclude_regex=False):
    order = ({"type": "column", "columnId": order_by_col} if order_by_col
             else {"type": "alphabetical", "fallback": True})
    return {
        "label": label or f"Top values of {field}", "dataType": "string",
        "operationType": "terms", "scale": "ordinal", "sourceField": field,
        "isBucketed": True, "customLabel": bool(label),
        "params": {"size": size, "orderBy": order,
                   "orderDirection": "desc" if order_by_col else "asc",
                   "otherBucket": other, "missingBucket": False,
                   "parentFormat": {"id": "terms"},
                   "include": [], "exclude": exclude or [],
                   "includeIsRegex": False, "excludeIsRegex": exclude_regex},
    }


def and_col_filter(columns, kql):
    """AND a KQL clause into every metric column's filter. Column-level
    filters keep working when a layer has ignoreGlobalFilters=true (which
    silences the panel-level query), so status panels scope through them."""
    for col in columns.values():
        if col.get("isBucketed") or col.get("operationType") in ("math",):
            continue
        old = (col.get("filter") or {}).get("query")
        col["filter"] = {"query": f"({old}) AND ({kql})" if old else kql,
                         "language": "kuery"}
    return columns


def col_eps_formula(label, ref_prefix, decimals=1):
    """Average events/sec over WHATEVER time range the panel is showing:
    count() / (time_range() / 1000). time_range() is the Lens formula
    context function returning the selected range in milliseconds, so this
    tile stays correct no matter what the user picks in the time filter."""
    formula = "count() / (time_range() / 1000)"
    return {
        ref_prefix: {
            "label": label, "dataType": "number", "operationType": "formula",
            "isBucketed": False, "scale": "ratio", "customLabel": True,
            "params": {"formula": formula, "isFormulaBroken": False,
                       "format": {"id": "number",
                                  "params": {"decimals": decimals,
                                             "compact": False}}},
            "references": [f"{ref_prefix}X2"],
        },
        f"{ref_prefix}X0": {
            "label": f"Part of {label}", "dataType": "number",
            "operationType": "count", "isBucketed": False, "scale": "ratio",
            "sourceField": "___records___", "customLabel": True,
            "params": {"emptyAsNull": False},
        },
        # time_range() compiles to its own hidden constant column that the
        # math column references (it is NOT a tinymath runtime function).
        f"{ref_prefix}X1": {
            "label": f"Part of {label}", "dataType": "number",
            "operationType": "time_range", "isBucketed": False,
            "scale": "ratio", "customLabel": True, "params": {},
            "references": [],
        },
        f"{ref_prefix}X2": {
            "label": f"Part of {label}", "dataType": "number",
            "operationType": "math", "isBucketed": False, "scale": "ratio",
            "customLabel": True,
            "params": {"tinymathAst": {
                "type": "function", "name": "divide",
                "args": [f"{ref_prefix}X0",
                         {"type": "function", "name": "divide",
                          "args": [f"{ref_prefix}X1", 1000],
                          "location": {"min": 9, "max": 30},
                          "text": "(time_range() / 1000)"}],
                "location": {"min": 0, "max": len(formula)},
                "text": formula}},
            "references": [f"{ref_prefix}X0", f"{ref_prefix}X1"],
        },
    }


def palette(stops_lohi):
    """stops_lohi: [(color, lower_bound), ...] ascending."""
    color_stops = [{"color": c, "stop": s} for c, s in stops_lohi]
    uppers = [s for _, s in stops_lohi[1:]] + [stops_lohi[-1][1] * 2 or 100]
    stops = [{"color": c, "stop": u}
             for (c, _), u in zip(stops_lohi, uppers)]
    return {"name": "custom", "type": "palette",
            "params": {"steps": len(stops_lohi), "name": "custom",
                       "reverse": False, "rangeType": "number",
                       "rangeMin": 0, "rangeMax": None,
                       "progression": "fixed", "stops": stops,
                       "colorStops": color_stops, "continuity": "above",
                       "maxSteps": 5}}


# --------------------------------------------------------------------------
# panel builders
# --------------------------------------------------------------------------
class Panel:
    def __init__(self, dv, title, grid, vis_type, vis, layers,
                 query="", time_range=None):
        """layers: {layer_id: {"columns": {...}, "order": [...]}}"""
        self.id = uid()
        self.dv = dv
        self.title = title
        self.grid = grid
        self.vis_type = vis_type
        self.vis = vis
        self.layers = layers
        self.query = query
        self.time_range = time_range

    def refs(self):
        return [{"type": "index-pattern", "id": self.dv,
                 "name": f"indexpattern-datasource-layer-{lid}"}
                for lid in self.layers]

    def to_json(self):
        ds_layers = {}
        ignore = self.dv in IGNORE_FILTER_DVS
        for lid, spec in self.layers.items():
            layer = {"columns": spec["columns"], "columnOrder": spec["order"],
                     "sampling": 1, "ignoreGlobalFilters": ignore,
                     "incompleteColumns": {}}
            if spec.get("link_to"):
                layer["linkToLayers"] = spec["link_to"]
            ds_layers[lid] = layer
        emb = {
            "attributes": {
                "title": "", "visualizationType": self.vis_type, "type": "lens",
                "references": self.refs(),
                "state": {
                    "visualization": self.vis,
                    "query": {"query": self.query, "language": "kuery"},
                    "filters": [],
                    "datasourceStates": {"formBased": {"layers": ds_layers}},
                    "internalReferences": [], "adHocDataViews": {},
                },
            },
            "hidePanelTitles": False, "enhancements": {},
        }
        if self.time_range:
            emb["timeRange"] = self.time_range
        x, y, w, h = self.grid
        return {"type": "lens",
                "gridData": {"x": x, "y": y, "w": w, "h": h, "i": self.id},
                "panelIndex": self.id, "embeddableConfig": emb,
                "title": self.title}


def metric(dv, title, grid, columns, order, accessor, query="",
           time_range=None, pal=None, secondary=None, subtitle=None,
           trendline=None):
    layer_id = uid()
    vis = {"layerId": layer_id, "layerType": "data",
           "metricAccessor": accessor, "showBar": False}
    if pal:
        vis["palette"] = pal
    if secondary:
        vis["secondaryMetricAccessor"] = secondary
    if subtitle:
        vis["subtitle"] = subtitle
    layers = {layer_id: {"columns": columns, "order": order}}
    if trendline:
        t_layer = uid()
        t_time, t_metric = uid(), uid()
        vis.update({"trendlineLayerId": t_layer,
                    "trendlineLayerType": "metricTrendline",
                    "trendlineTimeAccessor": t_time,
                    "trendlineMetricAccessor": t_metric})
        layers[t_layer] = {"columns": {t_time: col_date_hist(),
                                       t_metric: trendline},
                           "order": [t_time, t_metric],
                           "link_to": [layer_id]}
    return Panel(dv, title, grid, "lnsMetric", vis, layers, query, time_range)


def datatable(dv, title, grid, bucket_col, metric_cols, query="",
              bucket_id=None, time_range=None):
    layer_id = uid()
    b = bucket_id or uid()
    cols = {b: bucket_col}
    order = [b]
    vis_cols = [{"columnId": b}]
    for c in metric_cols:
        cid = uid()
        cols[cid] = c
        order.append(cid)
        vis_cols.append({"columnId": cid})
    vis = {"layerId": layer_id, "layerType": "data", "columns": vis_cols,
           "rowHeight": "single", "headerRowHeight": "single"}
    return Panel(dv, title, grid, "lnsDatatable", vis,
                 {layer_id: {"columns": cols, "order": order}},
                 query, time_range)


def xy_stacked(dv, title, grid, split_field, split_size=8, query="",
               time_range=None, legend_pos="bottom"):
    layer_id, x, y, s = uid(), uid(), uid(), uid()
    cols = {y: col_count("Events"),
            x: col_date_hist(),
            s: col_terms(split_field, order_by_col=y, size=split_size,
                         other=True)}
    vis = {"legend": {"isVisible": True, "position": legend_pos},
           "valueLabels": "hide", "fittingFunction": "None",
           "axisTitlesVisibilitySettings": {"x": False, "yLeft": False,
                                            "yRight": True},
           "tickLabelsVisibilitySettings": {"x": True, "yLeft": True,
                                            "yRight": True},
           "labelsOrientation": {"x": 0, "yLeft": 0, "yRight": 0},
           "gridlinesVisibilitySettings": {"x": True, "yLeft": True,
                                           "yRight": True},
           "preferredSeriesType": "bar_stacked",
           "layers": [{"layerId": layer_id, "accessors": [y],
                       "position": "top", "seriesType": "bar_stacked",
                       "showGridlines": False, "layerType": "data",
                       "xAccessor": x, "splitAccessor": s}]}
    return Panel(dv, title, grid, "lnsXY", vis,
                 {layer_id: {"columns": cols, "order": [s, x, y]}},
                 query, time_range)


def donut(dv, title, grid, field, size=8, query="", time_range=None):
    layer_id, g, m = uid(), uid(), uid()
    cols = {g: col_terms(field, order_by_col=m, size=size),
            m: col_count("Events")}
    vis = {"shape": "donut",
           "layers": [{"layerId": layer_id, "primaryGroups": [g],
                       "metrics": [m], "numberDisplay": "percent",
                       "categoryDisplay": "default",
                       "legendDisplay": "default", "nestedLegend": False,
                       "layerType": "data"}]}
    return Panel(dv, title, grid, "lnsPie", vis,
                 {layer_id: {"columns": cols, "order": [g, m]}},
                 query, time_range)


# --------------------------------------------------------------------------
# data views
# --------------------------------------------------------------------------
def data_view(dv_id, title, name, allow_hidden=False):
    return {
        "attributes": {"allowHidden": allow_hidden, "fieldAttrs": "{}",
                       "fieldFormatMap": "{}", "fields": "[]", "name": name,
                       "runtimeFieldMap": "{}", "sourceFilters": "[]",
                       "timeFieldName": "@timestamp", "title": title},
        "coreMigrationVersion": "8.8.0", "id": dv_id, "managed": False,
        "references": [], "type": "index-pattern",
        "typeMigrationVersion": "8.0.0",
    }


# --------------------------------------------------------------------------
# assemble
# --------------------------------------------------------------------------
def build_panels():
    panels = []
    m = uid  # shorthand

    # ---- Row 0: headline KPIs (y=0, h=8, 6 tiles) ----
    a = m()
    panels.append(metric(DV_LOGS, "Events (selected range)", (0, 0, 8, 8),
                         {a: col_count("Events")}, [a], a,
                         trendline=col_count("Events")))
    f = col_eps_formula("Avg events/sec", "eps", decimals=1)
    panels.append(metric(DV_LOGS, "Avg EPS (selected range)", (8, 0, 8, 8),
                         f, ["eps", "epsX0", "epsX1", "epsX2"], "eps"))
    a = m()
    panels.append(metric(DV_LOGS, "Active log sources (15m)", (16, 0, 8, 8),
                         {a: col_unique("service_name.keyword", "Sources")},
                         [a], a, time_range={"from": "now-15m", "to": "now"}))
    a = m()
    panels.append(metric(DV_ALERTS, "Open alerts (selected range)",
                         (24, 0, 8, 8),
                         and_col_filter(
                             {a: col_count("Open alerts", compact=False)},
                             'kibana.alert.workflow_status : "open"'),
                         [a], a,
                         query='kibana.alert.workflow_status : "open"',
                         pal=palette([(GREEN, 0), (YELLOW, 1), (RED, 50)])))
    a = m()
    panels.append(metric(DV_INTEL, "Threat intel IOCs (90d)", (32, 0, 8, 8),
                         {a: col_count("IOCs")}, [a], a,
                         time_range={"from": "now-90d", "to": "now"}))
    a, b = m(), m()
    panels.append(metric(DV_HEALTH, "SIEM status", (40, 0, 8, 8),
                         and_col_filter(
                             {a: col_last_str("status", "SIEM status"),
                              b: col_last_str("details", "Detail")},
                             'component : "overall"'),
                         [a, b], a, query='component : "overall"',
                         secondary=b, subtitle="from health collector"))

    # ---- Row 1: pipeline strip (y=8, h=7, health DV) ----
    a = m()
    panels.append(metric(DV_HEALTH, "Kafka consumer lag", (0, 8, 8, 7),
                         {a: col_last_num("kafka.total_lag", "Msgs behind",
                                          compact=True)}, [a], a,
                         query='component : "kafka"',
                         pal=palette([(GREEN, 0), (YELLOW, 10000),
                                      (RED, 100000)])))
    a = m()
    panels.append(metric(DV_HEALTH, "Parser throughput", (8, 8, 8, 7),
                         {a: col_last_num("parser.eps", "Events/sec",
                                          decimals=1)}, [a], a,
                         query='component : "parser-engine"'))
    a = m()
    panels.append(metric(DV_HEALTH, "Parser match rate", (16, 8, 8, 7),
                         {a: col_last_num("parser.match_rate", "Match rate",
                                          decimals=1, suffix="%")}, [a], a,
                         query='component : "parser-engine"',
                         pal=palette([(RED, 0), (YELLOW, 90), (GREEN, 98)])))
    a = m()
    panels.append(metric(DV_HEALTH, "Logstash output", (24, 8, 8, 7),
                         {a: col_last_num("logstash.out_rate", "Events/sec",
                                          decimals=1)}, [a], a,
                         query='component : "logstash"'))
    a = m()
    panels.append(metric(DV_HEALTH, "Elasticsearch heap", (32, 8, 8, 7),
                         {a: col_last_num("es.heap_percent", "Heap used",
                                          suffix="%")}, [a], a,
                         query='component : "elasticsearch"',
                         pal=palette([(GREEN, 0), (YELLOW, 70), (RED, 85)])))
    a = m()
    panels.append(metric(DV_HEALTH, "Storage used", (40, 8, 8, 7),
                         {a: col_last_num("es.disk_used_percent", "Disk used",
                                          suffix="%")}, [a], a,
                         query='component : "elasticsearch"',
                         pal=palette([(GREEN, 0), (YELLOW, 70), (RED, 85)])))

    # ---- Row 2: volume timeline + infrastructure table (y=15, h=14) ----
    panels.append(xy_stacked(DV_LOGS, "Log volume by source", (0, 15, 30, 14),
                             "service_name.keyword"))
    panels.append(datatable(
        DV_HEALTH, "Infrastructure components", (30, 15, 18, 14),
        col_terms("component", size=12, label="Component",
                  exclude=["source:.*"], exclude_regex=True),
        [col_last_str("status", "Status"),
         col_last_str("details", "Detail")],
        query='event.dataset : "tlsoc.health"'))

    # ---- Row 3: source freshness + volumes + share (y=29, h=13) ----
    panels.append(datatable(
        DV_HEALTH, "Log sources - freshness", (0, 29, 22, 13),
        col_terms("log_source.name", size=20, label="Source"),
        [col_last_str("status", "Status"),
         col_last_num("log_source.lag_seconds", "Sec since last event"),
         col_last_num("log_source.events_5m", "Events (5m)", compact=True),
         col_last_num("log_source.events_24h", "Events (24h)", compact=True)],
        query='event.dataset : "tlsoc.source_health"'))
    cnt = col_count("Events")
    panels.append(datatable(
        DV_LOGS, "Source volume (selected range)", (22, 29, 14, 13),
        col_terms("service_name.keyword", order_by_col="M1", size=10,
                  label="Source"),
        [], query=""))
    # add metric columns with known ids for orderBy
    p = panels[-1]
    lid = list(p.layers.keys())[0]
    p.layers[lid]["columns"]["M1"] = cnt
    p.layers[lid]["columns"]["M2"] = col_unique("source.ip", "Unique IPs",
                                                compact=True)
    p.layers[lid]["order"] += ["M1", "M2"]
    p.vis["columns"] += [{"columnId": "M1"}, {"columnId": "M2"}]
    panels.append(donut(DV_LOGS, "Share by source", (36, 29, 12, 13),
                        "service_name.keyword"))

    # ---- Row 4: alerts (y=42, h=13) ----
    panels.append(xy_stacked(DV_ALERTS, "Alerts by severity over time",
                             (0, 42, 24, 13), "kibana.alert.severity",
                             split_size=4))
    panels.append(datatable(
        DV_ALERTS, "Top alert rules", (24, 42, 14, 13),
        col_terms("kibana.alert.rule.name", order_by_col="M1", size=10,
                  label="Rule"),
        [], query=""))
    p = panels[-1]
    lid = list(p.layers.keys())[0]
    p.layers[lid]["columns"]["M1"] = col_count("Alerts", compact=False)
    p.layers[lid]["order"] += ["M1"]
    p.vis["columns"] += [{"columnId": "M1"}]
    panels.append(donut(DV_ALERTS, "Alerts by severity", (38, 42, 10, 13),
                        "kibana.alert.severity", size=4))

    # ---- Row 5: threat intel (y=55, h=12) ----
    panels.append(xy_stacked(DV_INTEL, "Threat intel ingested (30d)",
                             (0, 55, 24, 12), "intel_source.keyword",
                             split_size=6,
                             time_range={"from": "now-30d", "to": "now"}))
    panels.append(donut(DV_INTEL, "IOC types", (24, 55, 12, 12),
                        "ioc_type.keyword",
                        time_range={"from": "now-5y", "to": "now"}))
    panels.append(donut(DV_INTEL, "Intel feeds", (36, 55, 12, 12),
                        "intel_source.keyword",
                        time_range={"from": "now-5y", "to": "now"}))
    return panels


def build_control_group():
    """controlGroupInput attribute + the references its controls need."""
    control_panels, references = {}, []
    for order, c in enumerate(CONTROLS):
        cid = uid()
        control_panels[cid] = {
            "type": "optionsListControl", "order": order,
            "grow": True, "width": "medium",
            "explicitInput": {
                "id": cid, "dataViewId": DV_LOGS,
                "fieldName": c["field"], "title": c["title"],
                "searchTechnique": "prefix",
                "sort": {"by": "_count", "direction": "desc"},
                "selectedOptions": [], "existsSelected": False,
                "exclude": False, "enhancements": {},
            },
        }
        references.append({"type": "index-pattern", "id": DV_LOGS,
                           "name": f"controlGroup_{cid}:optionsListDataView"})
    group = {
        "controlStyle": "oneLine",
        "chainingSystem": "HIERARCHICAL",
        "showApplySelections": False,
        "ignoreParentSettingsJSON": json.dumps(
            {"ignoreFilters": False, "ignoreQuery": False,
             "ignoreTimerange": False, "ignoreValidations": False}),
        "panelsJSON": json.dumps(control_panels),
    }
    return group, references


def build_dashboard(panels):
    panels_json = [p.to_json() for p in panels]
    control_group, references = build_control_group()
    for p in panels:
        for r in p.refs():
            references.append({"type": "index-pattern", "id": r["id"],
                               "name": f"{p.id}:{r['name']}"})
    return {
        "attributes": {
            "title": "TLSOC - SOC Overview",
            "description": ("Landing dashboard: log onboarding volume, "
                            "pipeline & service health, log-source freshness, "
                            "alerts and threat intel. Health panels are fed by "
                            "monitoring/tlsoc_health_collector.py."),
            "kibanaSavedObjectMeta": {"searchSourceJSON": json.dumps(
                {"query": {"query": "", "language": "kuery"}, "filter": []})},
            "optionsJSON": json.dumps(
                {"useMargins": True, "syncColors": False, "syncCursor": True,
                 "syncTooltips": False, "hidePanelTitles": False}),
            "panelsJSON": json.dumps(panels_json),
            "controlGroupInput": control_group,
            "timeRestore": True, "timeFrom": "now-24h", "timeTo": "now",
            "refreshInterval": {"pause": False, "value": 60000},
            "version": 1,
        },
        "coreMigrationVersion": "8.8.0", "id": DASHBOARD_ID, "managed": False,
        "references": references, "type": "dashboard",
        "typeMigrationVersion": "8.9.0",
    }


def main():
    objects = [
        data_view(DV_LOGS, "fosstlsoc-logs-*", "TLSOC All Logs"),
        data_view(DV_HEALTH, "tlsoc-health-*", "TLSOC Health"),
        data_view(DV_ALERTS, f".alerts-security.alerts-{ARGS.space}",
                  "TLSOC Alerts", allow_hidden=True),
        data_view(DV_INTEL, "tlsoc-threat-intel*", "TLSOC Threat Intel"),
        build_dashboard(build_panels()),
    ]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        for o in objects:
            fh.write(json.dumps(o, separators=(",", ":")) + "\n")
    print(f"wrote {OUT} ({len(objects)} objects, "
          f"{len(json.loads(objects[-1]['attributes']['panelsJSON']))} panels)")


if __name__ == "__main__":
    main()
