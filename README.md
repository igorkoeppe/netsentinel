# NetSentinel

[![CI](https://github.com/igorkoeppe/netsentinel/actions/workflows/ci.yml/badge.svg)](https://github.com/igorkoeppe/netsentinel/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB.svg)

**English** · [Português (Brasil)](README.pt-BR.md)

NetSentinel is a defensive TCP monitoring and security observability tool. It
scans the ports you choose on hosts you are allowed to monitor, keeps a history
of every scan in PostgreSQL, detects changes between scans (a port that opens, a
host that goes down), turns those changes into security alerts with a triage
workflow, and notifies you through webhooks. You can drive it from a CLI, a
versioned REST API or a React dashboard.

It started as a Computer Engineering project focused on cybersecurity, and it is
built like a small production service: async Python, a layered architecture,
database migrations, a least-privilege database role, an authenticated API, and
CI that runs linting, type checking, unit, integration and frontend tests.

> [!IMPORTANT]
> NetSentinel is for education and defense. Only scan systems you own or have
> explicit permission to test. See [Responsible use](#responsible-use).

<!--
  SCREENSHOT PLACEHOLDER: dashboard overview.
  Add the image (suggested path: docs/images/dashboard-overview.png) and uncomment:
  ![NetSentinel dashboard overview](docs/images/dashboard-overview.png)
-->

## Features

- **CLI** (`netsentinel`) for one-off scans, continuous monitoring, history,
  alert triage and scheduled scans.
- **Async TCP scanner** with strict target validation (IPv4, IPv6, hostnames),
  bounded concurrency and per-port latency. Ports are reported as `OPEN`,
  `CLOSED`, `TIMEOUT` or `UNREACHABLE`; host availability and response time are
  inferred from the TCP handshake.
- **Change detection**: consecutive snapshots are compared to emit
  `PORT_OPENED`, `PORT_CLOSED`, `HOST_BECAME_AVAILABLE` and
  `HOST_BECAME_UNAVAILABLE` events. The first snapshot only sets a baseline, so
  there are no false positives on start.
- **Security alerts** from deterministic rules (`NEW_OPEN_PORT`,
  `UNEXPECTED_OPEN_PORT`, `EXPECTED_OPEN_PORT`, `PORT_CLOSED`, `HOST_DOWN`,
  `HOST_RECOVERED`) with configurable severities and an expected-ports policy
  (`EXPECTED_TCP_PORTS`).
- **Alert triage** lifecycle `OPEN → ACKNOWLEDGED → RESOLVED`, available in the
  CLI, the API and the dashboard, with invalid transitions rejected.
- **Webhook notifications** above a minimum severity, with sanitized payloads,
  timeouts, and every delivery attempt audited in the database.
- **Scheduled scans**: one periodic scan per host, run by a scheduler that can
  safely run in several processes at once (`FOR UPDATE SKIP LOCKED`).
- **REST API** (`/api/v1`, FastAPI) with OpenAPI docs, `X-API-Key`
  authentication, health and readiness probes, and opt-in strict CORS.
- **Web dashboard** (React 18 + TypeScript strict) with an overview, charts,
  alert queue and triage, hosts, scans, schedules and settings, in dark and
  light themes.
- **PostgreSQL persistence** with SQLAlchemy 2 (async) and Alembic migrations;
  the app connects with a non-admin role and migrations run as the owner.

## Architecture

```text
   ┌───────────┐    ┌──────────────────┐   ┌──────────────────────────┐
   │    CLI    │    │    Scheduler     │   │ Dashboard (React + TS)   │
   │netsentinel│    │ (CLI or in API)  │   │ Nginx, same-origin /api  │
   └─────┬─────┘    └────────┬─────────┘   └────────────┬─────────────┘
         │                   │                          │ HTTP/JSON + X-API-Key
         │                   │                          ▼
         │                   │             ┌──────────────────────────┐
         │                   │             │ REST API /api/v1 FastAPI │
         │                   │             └────────────┬─────────────┘
         ▼                   ▼                          ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │ Monitoring: target validation · async TCP probes · port scanner  │
   │ Detection:  snapshot diff → events → alert rules                 │
   │ Services:   history, alert query/triage, scheduling, delivery    │
   │ Notifications: severity policy → webhook sender                  │
   └───────────────────────────────┬──────────────────────────────────┘
                                   ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │ Repositories / SQLAlchemy models (hosts, scans, port results,    │
   │ events, alerts, notification deliveries, schedules)              │
   └───────────────────────────────┬──────────────────────────────────┘
                                   ▼
                       PostgreSQL 16 (Alembic migrations)
```

The CLI and the API share the same services, so business rules such as alert
transitions live in one place.

| Path | Contents |
| --- | --- |
| `app/monitoring/` | Target parsing, TCP probe, port scanner, monitor loop, scheduler |
| `app/detection/` | Change detection engine and alert rules |
| `app/notifications/` | Notification policy, dispatcher and webhook sender |
| `app/services/`, `app/repositories/`, `app/models/` | Application services, data access and ORM models |
| `app/api/` | FastAPI routes, schemas, auth and error handling |
| `app/cli.py` | The `netsentinel` command |
| `frontend/` | React dashboard (Vite, TanStack Query, Recharts) |
| `migrations/` | Alembic migrations |

## Quick start

Requirements: Python 3.12+, Docker with Docker Compose, and Git. The commands
below are for Linux/macOS; on Windows PowerShell, activate the virtual
environment with `.venv\Scripts\Activate.ps1` and run the rest as written.

```bash
# 1. Get the code and install the CLI
git clone https://github.com/igorkoeppe/netsentinel.git
cd netsentinel
python -m venv .venv
source .venv/bin/activate
pip install -e .

# 2. Create .env with random database passwords and an API_KEY
python -m tools.init_env

# 3. Start PostgreSQL and create the schema
docker compose up -d --wait db
alembic upgrade head

# 4. Start the API and the dashboard
docker compose --profile web up --build -d --wait
```

Then open:

- Dashboard: <http://127.0.0.1:3000>. Paste the `API_KEY` value from `.env`
  into **Settings** (or the sign-in prompt).
- API docs (Swagger UI): <http://127.0.0.1:8000/docs>

Every port is published on `127.0.0.1` only. `tools.init_env` copies
`.env.example` and fills in `POSTGRES_PASSWORD`, `NETSENTINEL_DB_PASSWORD`,
`DATABASE_URL`, `MIGRATION_DATABASE_URL` and `API_KEY`; it never overwrites an
existing `.env`. Never commit `.env`.

Generate some data from the CLI, then refresh the dashboard:

```bash
netsentinel monitor 127.0.0.1 --ports 22,80,443,5432 --interval 5 --count 3 --persist
```

To stop everything: `docker compose --profile web down` (add `-v` to also delete
the database volume).

> Only want to scan? `pip install -e .` and `netsentinel scan 127.0.0.1 --ports 22,80,443`
> work without Docker or a database.

## CLI usage

<!--
  GIF PLACEHOLDER: CLI demo (scan, monitor with alerts, alerts triage).
  Add the recording (suggested path: docs/images/cli-demo.gif) and uncomment:
  ![NetSentinel CLI demo](docs/images/cli-demo.gif)
-->

Every command has `--help`. Commands marked with *DB* need PostgreSQL and the
migrations from the Quick start.

### Scan

```bash
netsentinel scan 127.0.0.1 --ports 22,80,443,8000
```

```text
NetSentinel TCP Scan

Target: 127.0.0.1
Status: AVAILABLE
Response time: 1.0 ms

PORT     STATUS       TIME
22       CLOSED       2.1 ms
80       CLOSED       1.9 ms
443      CLOSED       1.8 ms
8000     OPEN         1.0 ms

4 ports scanned
1 open
3 closed
```

### Monitor

```bash
# Scan every 30 s until Ctrl+C, printing events and alerts as they happen
netsentinel monitor 127.0.0.1 --ports 22,80,443 --interval 30

# Stop after 10 snapshots and save every cycle to PostgreSQL (DB)
netsentinel monitor 127.0.0.1 --ports 80,443 --interval 5 --count 10 --persist
```

The monitor prints a session summary at the end (snapshots, events, alerts by
severity, duration). Without `--persist` everything stays in memory; with it,
each cycle (scan, port results, events, alerts) is written atomically, and
alerts are sent to the webhook if one is configured.

### History (DB)

```bash
netsentinel history 127.0.0.1            # latest 10 scans of a host
netsentinel history 127.0.0.1 --limit 5
netsentinel history --scan 42            # ports, events and alerts of one scan
```

### Alerts and triage (DB)

```bash
netsentinel alerts                                   # latest 20 alerts
netsentinel alerts --status OPEN --severity HIGH --limit 10
netsentinel alerts acknowledge 42                    # OPEN -> ACKNOWLEDGED
netsentinel alerts resolve 42                        # OPEN/ACKNOWLEDGED -> RESOLVED
```

```text
NetSentinel Security Alerts

ID     SEVERITY   TYPE                   STATUS         TARGET           PORT     CREATED
42     HIGH       UNEXPECTED_OPEN_PORT   OPEN           127.0.0.1        8080     2026-09-08 15:30:00
41     LOW        PORT_CLOSED            ACKNOWLEDGED   127.0.0.1        22       2026-09-08 15:20:00
40     MEDIUM     HOST_DOWN              RESOLVED       127.0.0.1        -        2026-09-08 15:00:00
```

`--status` accepts `OPEN`, `ACKNOWLEDGED`, `RESOLVED`; `--severity` accepts
`INFO`, `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` (both case-insensitive).

### Scheduled scans (DB)

```bash
netsentinel schedule add 192.168.1.10 --ports 22,80,443 --interval 300
netsentinel schedule list
netsentinel schedule update 1 --interval 900
netsentinel schedule disable 1
netsentinel schedule enable 1      # becomes due immediately
netsentinel schedule run           # run the scheduler in the foreground (Ctrl+C to stop)
netsentinel schedule run --once    # run what is due now and exit (e.g. from cron)
```

Each run is stored as a regular scan and compared with the host's previous
scan, so new open ports and closed ports raise alerts and webhooks just like
`monitor --persist`. The scheduler can also run inside the API process with
`SCHEDULER_ENABLED=true`.

## Web dashboard

<!--
  SCREENSHOT PLACEHOLDERS: add the images (suggested paths below) and uncomment.
  ![Alert queue](docs/images/dashboard-alerts.png)
  ![Alert details and triage](docs/images/dashboard-alert-details.png)
  ![Scan details](docs/images/dashboard-scan-details.png)
-->

| Page | What it shows |
| --- | --- |
| Overview | Host, scan and alert counters, alerts by status and severity, latest alerts and scans, API and database health |
| Alerts / Alert details | Filterable, paginated alert queue (filters synced to the URL), acknowledge and resolve with confirmation, webhook delivery history |
| Hosts / Host details | Searchable host list and the scan history of each host |
| Scans / Scan details | All scans, and each scan's ports, events and alerts |
| Schedules | Create, enable and disable scheduled scans; see the last run or error |
| Settings | API key (kept in memory, or in `sessionStorage` if you choose), theme, polling interval |

For frontend development with hot reload, run the API with
`uvicorn app.main:app --reload` and, in `frontend/`, `npm install && npm run dev`
(Vite proxies `/api` to port 8000).

## REST API

Interactive docs are at `/docs` (Swagger UI) and `/redoc`. With `API_KEY` set,
every endpoint except health checks requires the `X-API-Key` header. Without
it (local development), reads are public and mutations return `503`.

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/api/v1/health/live`, `/api/v1/health/ready` | Liveness and readiness (always public) |
| `GET` | `/api/v1/dashboard/summary` | Aggregate counters for the dashboard |
| `GET` | `/api/v1/hosts`, `/api/v1/hosts/{target}/history` | Hosts (search with `q`) and a host's scans |
| `GET` | `/api/v1/scans`, `/api/v1/scans/{scan_id}` | Scans and scan details |
| `GET` | `/api/v1/alerts`, `/api/v1/alerts/summary`, `/api/v1/alerts/{id}` | Alert queue (`status`, `severity`, `type`, `target`), counts, details |
| `GET` | `/api/v1/alerts/{id}/deliveries` | Webhook delivery attempts for an alert |
| `POST` | `/api/v1/alerts/{id}/acknowledge`, `/api/v1/alerts/{id}/resolve` | Triage (`409` on invalid transitions) |
| `GET`, `POST` | `/api/v1/schedules` | List or create scheduled scans |
| `GET`, `PATCH` | `/api/v1/schedules/{id}` | Read or change a schedule |

```bash
curl -s -H "X-API-Key: $API_KEY" \
  "http://127.0.0.1:8000/api/v1/alerts?status=OPEN&severity=HIGH&limit=20"
```

## Configuration

Settings come from environment variables or `.env`; [`.env.example`](.env.example)
documents all of them. The most relevant:

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | empty | Runtime connection (non-admin `netsentinel_app` role). Empty disables persistence. |
| `MIGRATION_DATABASE_URL` | empty | Owner connection used by Alembic |
| `API_KEY` | empty | Key required in `X-API-Key` |
| `API_CORS_ORIGINS` | empty | Explicit allowed origins; `*` is rejected |
| `EXPECTED_TCP_PORTS` | empty | Ports that are allowed to open (`EXPECTED_OPEN_PORT` vs `UNEXPECTED_OPEN_PORT`) |
| `ALERT_SEVERITY_*` | per rule | Severity of each alert rule |
| `NOTIFICATION_WEBHOOK_URL` | empty | Webhook that receives alerts (HTTP POST, JSON) |
| `NOTIFICATION_MIN_SEVERITY` | `HIGH` | Lowest severity that triggers a notification |
| `SCAN_TIMEOUT`, `SCAN_MAX_CONCURRENCY` | `3.0`, `50` | Probe timeout and concurrency |
| `SCHEDULER_ENABLED` | `false` | Run the scheduler inside the API |

## Development

```bash
pip install -e ".[dev]"
ruff check . && ruff format --check .
mypy app
pytest -m "not integration"     # unit tests, no database or network needed
```

Integration tests need a PostgreSQL database named `netsentinel_test` and
`TEST_DATABASE_URL`; see [README.pt-BR.md](README.pt-BR.md#desenvolvimento).
[CI](.github/workflows/ci.yml) runs lint and types, unit tests, integration
tests against PostgreSQL 16 (including `alembic check`), and the frontend lint,
type check and tests on every push to `main` and every pull request.

## Limitations

NetSentinel is not an IDS/IPS or a vulnerability scanner. It does not do ICMP
or UDP probes, subnet discovery, service or OS fingerprinting, or exploitation,
and webhooks are the only notification channel for now. The single API key is
meant for labs and controlled networks; put TLS and a real identity provider in
front of it before exposing it.

## Responsible use

Use NetSentinel only on systems you own, on `localhost` and lab environments,
in authorized CTFs, or on networks where you have prior, explicit permission.
Scanning networks without authorization may be illegal and is against the
purpose of this project.

## License

[MIT](LICENSE) © igorkoeppe. The license grants the usual MIT permissions; the
[responsible-use notice](#responsible-use) describes how the project is meant to
be used.
