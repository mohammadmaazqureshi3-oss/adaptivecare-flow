"""Configuration that cannot run here without Docker, checked for consistency with the code:
Prometheus, Grafana (MON-03, plan Section 9) and the HTTPS web server (plan C4-03)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]
NOT_SCRAPED = {"postgres", "rabbitmq", "web", "prometheus", "grafana", "engine"}
# Metric names the services produce (service_metrics.Metrics and the services' gauges) or Prometheus adds.
PRODUCED = {"http_requests_total", "http_request_duration_seconds", "http_request_duration_seconds_bucket",
            "process_uptime_seconds", "worklist_open_tasks", "worklist_alerts_pending",
            "engine_running_cases", "up"}  # fmt: skip
FUNCTIONS = {
    "sum",
    "by",
    "rate",
    "increase",
    "histogram_quantile",
    "topk",
    "le",
    "service",
    "route",
    "status",
    "job",
}


def test_mon03_prometheus_scrapes_every_service() -> None:
    config = yaml.safe_load((ROOT / "monitoring" / "prometheus.yml").read_text())
    targets = {
        t.split(":")[0]
        for job in config["scrape_configs"]
        for sc in job["static_configs"]
        for t in sc["targets"]
    }
    assert targets == set(COMPOSE) - NOT_SCRAPED


def test_mon03_grafana_dashboard_only_queries_metrics_the_services_produce() -> None:
    dash = json.loads(
        (ROOT / "monitoring" / "grafana" / "dashboards" / "adaptivecare-services.json").read_text()
    )
    source = yaml.safe_load(
        (ROOT / "monitoring" / "grafana" / "provisioning" / "datasources" / "prometheus.yml").read_text()
    )["datasources"][0]
    exprs = [t["expr"] for p in dash["panels"] for t in p["targets"]]
    assert exprs and all(p["datasource"]["uid"] == source["uid"] for p in dash["panels"])
    for expr in exprs:
        names = set(re.findall(r"[a-z_][a-z0-9_]*", re.sub(r'"[^"]*"|\[[^\]]*\]|\{\{[^}]*\}\}', "", expr)))
        assert names - FUNCTIONS <= PRODUCED, expr
    assert source["url"] == "http://prometheus:9090" and "prometheus" in COMPOSE
    assert COMPOSE["grafana"]["profiles"] == ["monitoring"]


def test_c4_03_the_web_server_serves_https_with_the_generated_or_mounted_certificate() -> None:
    conf = (ROOT / "web" / "nginx.conf.template").read_text()
    script = (ROOT / "web" / "10-tls-cert.sh").read_text()
    assert "listen 443 ssl;" in conf and "return 301 https://" in conf
    assert "ssl_protocols       TLSv1.2 TLSv1.3;" in conf and "Strict-Transport-Security" in conf
    for name in ("cert.pem", "key.pem"):
        assert f"/etc/nginx/tls/{name}" in conf and f'"$dir/{name}"' in script
    assert "dir=/etc/nginx/tls" in script
    assert "8443:443" in COMPOSE["web"]["ports"] and COMPOSE["web"]["environment"]["HTTPS_PORT"] == "8443"
