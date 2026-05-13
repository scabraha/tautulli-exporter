# Tautulli Prometheus Exporter

A lightweight Prometheus exporter that polls the [Tautulli](https://tautulli.com/) API for Plex playback activity, library statistics, and per-session GeoIP data.

Tautulli does not ship Prometheus metrics out of the box. This exporter fills that gap by polling Tautulli's REST API and exposing playback, bandwidth, and library data as Prometheus metrics suitable for Grafana dashboards.

## Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `tautulli_session_count` | Gauge | — | Active Plex sessions |
| `tautulli_sessions_by_decision` | Gauge | `decision` | Active sessions by transcode decision (`direct play`, `copy`, `transcode`) |
| `tautulli_session_bandwidth_bytes` | Gauge | `scope` | Current bandwidth in bytes/s by `scope` (`total`, `lan`, `wan`) |
| `tautulli_session_info` | Gauge | `user`, `player`, `platform`, `quality`, `title`, `decision`, `ip` | Per-session info; value is the session's bandwidth in bytes/s |
| `tautulli_session_geo` | Gauge | `user`, `title`, `decision`, `city`, `region`, `country`, `latitude`, `longitude` | Per-session geolocation (only when `GEOIP_ENABLED=true`); value is `1` |
| `tautulli_libraries_total` | Gauge | — | Total Plex libraries Tautulli is tracking |
| `tautulli_library_items` | Gauge | `name`, `type` | Items in each Plex library |
| `tautulli_exporter_poll_duration_seconds` | Gauge | — | Wall-clock duration of the most recent poll cycle |
| `tautulli_exporter_poll_failures_total` | Counter | `step` | Poll cycles that ended in failure, labelled by step (`version`, `libraries`, `activity`) |
| `tautulli_exporter_last_successful_poll_timestamp_seconds` | Gauge | — | Unix timestamp of the most recent successful poll |
| `tautulli_exporter_geoip_lookups_total` | Counter | `result` | GeoIP lookups attempted (`hit` / `miss`) |
| `tautulli_plex_version_info` | Info | `version`, `server_name` | Connected Plex Media Server version |
| `tautulli_up` | Gauge | — | Whether the exporter can reach Tautulli |

> Bandwidth values from Tautulli arrive as kilobits per second; the exporter converts them to bytes per second so they line up with Prometheus' `bytes`/`bytes_per_second` conventions.

## Quick Start

### Docker Compose

```yaml
services:
  tautulli-exporter:
    image: ghcr.io/scabraha/tautulli-exporter:latest
    container_name: tautulli-exporter
    restart: unless-stopped
    env_file: .env
    ports:
      - 9487:9487
```

`.env`:

```env
TAUTULLI_URL=http://tautulli:8181
TAUTULLI_API_KEY=your_tautulli_api_key_here
```

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TAUTULLI_URL` | Yes | — | Base URL of the Tautulli instance |
| `TAUTULLI_API_KEY` | Yes | — | Tautulli API key (Settings → Web Interface → API) |
| `EXPORTER_PORT` | No | `9487` | Port to listen on |
| `POLL_INTERVAL` | No | `30` | Seconds between API polls |
| `REQUEST_TIMEOUT` | No | `10` | HTTP request timeout (seconds) |
| `GEOIP_ENABLED` | No | `true` | Resolve session IPs via Tautulli's GeoIP API and emit `tautulli_session_geo` |
| `GEOIP_CACHE_TTL` | No | `3600` | Seconds to cache each GeoIP lookup |
| `LOG_LEVEL` | No | `INFO` | Log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `LOG_FORMAT` | No | `text` | `text` for human-readable lines, `json` for one JSON object per line (Loki/CloudWatch friendly) |

## GeoIP

GeoIP labels (`country`, `city`, `region`, `latitude`, `longitude`) are populated by Tautulli itself — no MaxMind database needs to be mounted into the exporter container. As long as Tautulli is configured with an active GeoIP database (Settings → General → GeoLite2), `tautulli_session_geo` will fire for every active session with an external IP.

Lookups for private/loopback/link-local IPs are skipped client-side because GeoIP can't usefully resolve them. Both hits and misses are cached for `GEOIP_CACHE_TTL` seconds so a long-running session doesn't re-query Tautulli on every poll.

To suppress the metric entirely (and the corresponding Tautulli API calls), set `GEOIP_ENABLED=false`.

### Cardinality notes

`tautulli_session_info` and `tautulli_session_geo` carry per-session labels (`user`, `title`, IP). For typical home/small-team Plex deployments this is fine. If you have hundreds of concurrent unique titles being played, watch the time-series count and consider scraping less frequently or dropping high-churn labels via Prometheus relabelling.

## Observability

The exporter publishes self-monitoring metrics so you can alert on it being broken (not just on Tautulli being broken):

```promql
# Tautulli is unreachable for 5+ minutes
max_over_time(tautulli_up[5m]) == 0

# Last successful poll was > 5 minutes ago
time() - tautulli_exporter_last_successful_poll_timestamp_seconds > 300

# Sustained poll failures
rate(tautulli_exporter_poll_failures_total[10m]) > 0
```

Logs use a structured key=value style at INFO and below; switch to JSON via `LOG_FORMAT=json` for log aggregators. Set `LOG_LEVEL=DEBUG` to also see per-request HTTP timings and GeoIP lookup results.

## Creating an API Key

1. Log into Tautulli
2. Go to Settings → Web Interface
3. Scroll to "API" and copy the key (or click "Generate" if one doesn't exist)

## Prometheus Scrape Config

```yaml
scrape_configs:
  - job_name: "tautulli"
    static_configs:
      - targets: ["tautulli-exporter:9487"]
```

## Building & Testing

```bash
# Run tests
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest

# Build container image
docker build -t tautulli-exporter .
```

## Releases

Releases are automated by [release-please](https://github.com/googleapis/release-please) using [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` → minor bump
- `fix:` / `perf:` → patch bump
- `feat!:` or `BREAKING CHANGE:` footer → major bump

On each push to `main`, release-please opens or updates a release PR with the new version and changelog. Merging it tags the release and publishes a multi-arch (`linux/amd64`, `linux/arm64`) image to `ghcr.io/scabraha/tautulli-exporter` with tags `vX.Y.Z`, `X.Y`, `X`, and `latest`.

## License

MIT
