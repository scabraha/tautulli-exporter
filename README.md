# Tautulli Prometheus Exporter

A lightweight Prometheus exporter that polls the [Tautulli](https://tautulli.com/) API for Plex playback activity, library statistics, user engagement, and per-session GeoIP data.

Tautulli does not ship Prometheus metrics out of the box. This exporter fills that gap by polling Tautulli's REST API and exposing playback, bandwidth, library, and user data as Prometheus metrics suitable for Grafana dashboards.

## Tiered polling

To avoid wasting calls on slow-changing data while still surfacing fresh activity, the exporter runs three independent loops:

| Tier | Default interval | What runs | Why |
|------|------------------|-----------|-----|
| **activity** | `10s` | `get_activity` + `server_status` + GeoIP lookups | All in-memory on Tautulli's side; safe to poll often. Drives the heartbeat (`tautulli_up`). |
| **inventory** | `300s` (5 min) | `get_libraries_table` + `get_users_table` + `get_users` + `get_server_info` | Hits Tautulli's SQLite. Library/user counts and lifetime stats don't need sub-minute resolution. |
| **meta** | `1800s` (30 min) | `get_pms_update` | Calls plex.tv via Tautulli — kept slow to be a polite client. |

Each tier reports failures independently via `tautulli_exporter_poll_failures_total{step=...}`, so an inventory blip doesn't flip the up/down signal that monitors the fast loop.

## Metrics

### Activity (refreshed every `ACTIVITY_POLL_INTERVAL`)

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `tautulli_session_count` | Gauge | — | Active Plex sessions |
| `tautulli_sessions_by_decision` | Gauge | `decision` | Sessions by transcode decision (`direct play` / `direct stream` / `copy` / `transcode`) |
| `tautulli_sessions_by_state` | Gauge | `state` | Sessions by player state (`playing` / `paused` / `buffering`) |
| `tautulli_sessions_by_location` | Gauge | `location` | Sessions by network location (`lan` / `wan` / `relay`) |
| `tautulli_sessions_by_media_type` | Gauge | `media_type` | Sessions by media type (`movie` / `episode` / `track` / `live` / `clip`) |
| `tautulli_sessions_secure` | Gauge | — | Sessions using a TLS-encrypted connection to Plex |
| `tautulli_session_bandwidth_bytes` | Gauge | `scope` | Current bandwidth in bytes/s (`total` / `lan` / `wan`) |
| `tautulli_session_info` | Gauge | `user`, `player`, `platform`, `quality`, `title`, `decision`, `ip` | Per-session info; value is the session's bandwidth in bytes/s |
| `tautulli_session_progress_ratio` | Gauge | `user`, `title` | Playback position (0.0 – 1.0) |
| `tautulli_session_transcode_speed_ratio` | Gauge | `user`, `title` | Transcoder speed; `< 1.0` means falling behind real-time |
| `tautulli_session_throttled` | Gauge | `user`, `title` | `1` when the transcoder is throttled (client buffer full) |
| `tautulli_session_transcode_hw` | Gauge | `user`, `title`, `direction` | `1` when HW-accelerated `decode` / `encode` is active |
| `tautulli_session_geo` | Gauge | `user`, `title`, `decision`, `city`, `region`, `country`, `latitude`, `longitude` | Per-session geo (only when `GEOIP_ENABLED=true`); value is `1` |
| `tautulli_plex_reachable` | Gauge | — | `1` if Tautulli currently has a working connection to Plex |

### Inventory (refreshed every `INVENTORY_POLL_INTERVAL`)

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `tautulli_libraries_total` | Gauge | — | Total Plex libraries Tautulli is tracking |
| `tautulli_library_items` | Gauge | `name`, `type` | Items in a Plex library (movies / shows / artists, depending on type) |
| `tautulli_library_seasons` | Gauge | `name`, `type` | Parent count (seasons for shows, albums for music) |
| `tautulli_library_episodes` | Gauge | `name`, `type` | Child count (episodes for shows, tracks for music) |
| `tautulli_library_plays` | Gauge | `name`, `type` | All-time play count for the library |
| `tautulli_library_play_duration_seconds` | Gauge | `name`, `type` | All-time watch seconds for the library |
| `tautulli_library_last_accessed_timestamp_seconds` | Gauge | `name`, `type` | Unix timestamp of the most recent play |
| `tautulli_library_active` | Gauge | `name`, `type` | `1` if the library is currently active in Plex |
| `tautulli_library_size_bytes` | Gauge | `name`, `type` | Total on-disk size — only emitted when `LIBRARY_SIZE_ENABLED=true` |
| `tautulli_users_total` | Gauge | — | Total Plex users known to Tautulli |
| `tautulli_users_active` | Gauge | — | Plex users currently flagged active |
| `tautulli_users_home` | Gauge | — | Plex Home (family) users |
| `tautulli_user_last_seen_timestamp_seconds` | Gauge | `user` | Unix timestamp of the user's most recent session |
| `tautulli_user_plays` | Gauge | `user` | All-time play count per user |
| `tautulli_user_play_duration_seconds` | Gauge | `user` | All-time watch seconds per user |
| `tautulli_plex_version` | Info | `version`, `server_name` | Connected Plex Media Server version |

### Meta (refreshed every `META_POLL_INTERVAL`)

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `tautulli_plex_update_available` | Gauge | — | `1` if Plex Media Server has an update pending |
| `tautulli_plex_update` | Info | `version`, `release_date`, `platform` | Details of the latest available PMS update |

### Self-monitoring

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `tautulli_up` | Gauge | — | Whether the exporter can reach Tautulli (driven by the activity tier) |
| `tautulli_exporter_poll_duration_seconds` | Gauge | — | Wall-clock duration of the most recent activity poll |
| `tautulli_exporter_poll_failures_total` | Counter | `step` | Poll steps that ended in failure (`activity`, `status`, `inventory`, `meta`) |
| `tautulli_exporter_last_successful_poll_timestamp_seconds` | Gauge | — | Unix timestamp of the most recent successful activity poll |
| `tautulli_exporter_geoip_lookups_total` | Counter | `result` | GeoIP lookups attempted (`hit` / `miss`) |

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
| `ACTIVITY_POLL_INTERVAL` | No | `10` | Seconds between activity-tier polls |
| `INVENTORY_POLL_INTERVAL` | No | `300` | Seconds between inventory-tier polls |
| `META_POLL_INTERVAL` | No | `1800` | Seconds between meta-tier polls |
| `REQUEST_TIMEOUT` | No | `10` | HTTP request timeout (seconds) |
| `GEOIP_ENABLED` | No | `true` | Resolve session IPs via Tautulli's GeoIP API and emit `tautulli_session_geo` |
| `GEOIP_CACHE_TTL` | No | `3600` | Seconds to cache each GeoIP lookup |
| `LIBRARY_SIZE_ENABLED` | No | `false` | Emit `tautulli_library_size_bytes`. Calls `get_library_media_info` per library — slow on huge libraries. |
| `LOG_LEVEL` | No | `INFO` | Log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `LOG_FORMAT` | No | `text` | `text` for human-readable lines, `json` for one JSON object per line (Loki/CloudWatch friendly) |

> **Migrating from `POLL_INTERVAL`:** `POLL_INTERVAL` was removed in the tiered-polling refactor. Replace it with `ACTIVITY_POLL_INTERVAL` (or just drop it — the new defaults give you fresher activity metrics with fewer total API calls).

## GeoIP

GeoIP labels (`country`, `city`, `region`, `latitude`, `longitude`) are populated by Tautulli itself — no MaxMind database needs to be mounted into the exporter container. As long as Tautulli is configured with an active GeoIP database (Settings → General → GeoLite2), `tautulli_session_geo` will fire for every active session with an external IP.

Lookups for private/loopback/link-local IPs are skipped client-side because GeoIP can't usefully resolve them. Both hits and misses are cached for `GEOIP_CACHE_TTL` seconds so a long-running session doesn't re-query Tautulli on every poll.

To suppress the metric entirely (and the corresponding Tautulli API calls), set `GEOIP_ENABLED=false`.

### Cardinality notes

`tautulli_session_info` and `tautulli_session_geo` carry per-session labels (`user`, `title`, IP). For typical home/small-team Plex deployments this is fine. If you have hundreds of concurrent unique titles being played, watch the time-series count and consider scraping less frequently or dropping high-churn labels via Prometheus relabelling.

Per-user metrics (`tautulli_user_*`) and per-library metrics (`tautulli_library_*`) scale with your user/library counts — typically <50 and <20 respectively, so they're trivial.

## Observability

The exporter publishes self-monitoring metrics so you can alert on it being broken (not just on Tautulli being broken):

```promql
# Tautulli is unreachable for 5+ minutes
max_over_time(tautulli_up[5m]) == 0

# Tautulli is up but Plex is down
tautulli_up == 1 and tautulli_plex_reachable == 0

# Last successful activity poll was > 5 minutes ago
time() - tautulli_exporter_last_successful_poll_timestamp_seconds > 300

# Sustained poll failures, by tier
rate(tautulli_exporter_poll_failures_total[10m]) > 0

# Plex Media Server has an update pending
tautulli_plex_update_available == 1

# Transcode is falling behind real-time
tautulli_session_transcode_speed_ratio < 1
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
PYTHONPATH=. .venv/bin/pytest

# Build container image
docker build -t tautulli-exporter .
```

PRs are gated by [`.github/workflows/test.yml`](.github/workflows/test.yml), which runs `pytest` on Python 3.10, 3.11, and 3.12.

## Releases

Releases are automated by [release-please](https://github.com/googleapis/release-please) using [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` → minor bump
- `fix:` / `perf:` → patch bump
- `feat!:` or `BREAKING CHANGE:` footer → major bump

On each push to `main`, release-please opens or updates a release PR with the new version and changelog. Merging it tags the release and publishes a multi-arch (`linux/amd64`, `linux/arm64`) image to `ghcr.io/scabraha/tautulli-exporter` with tags `vX.Y.Z`, `X.Y`, `X`, and `latest`.

## License

MIT
