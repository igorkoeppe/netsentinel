# Changelog

## [0.4.0] - Unreleased

### Added
- Security alert domain model (`SecurityAlert`, `AlertType`, `Severity`).
- Initial alert rules for host and TCP port state changes.
- Created Alert Engine (`AlertEngine`) as a pure domain service to transform `MonitoringEvent`s into `SecurityAlert`s based on detection rules (`DetectionRule`).
- Transactional persistence of security alerts with monitoring cycles.
- Persistent security alert storage during `netsentinel monitor --persist`.
- Real-time security alert generation during continuous monitoring.
- Monitoring session alert summaries grouped by severity.
- Unit tests for all four alert rules, ordering, timestamp/target/port preservation, and edge cases.
- `AlertRepository` extensions for ordering by `created_at ASC, id ASC` on scan lookup and batch counting via `count_by_scans` without N+1 queries.
- Integration of persisted security alerts into `HistoryService` (`get_scan_details` includes `AlertSummary` list; `get_host_history` includes `alert_count` per scan).
- Updated CLI `netsentinel history` to display `ALERTS` column in host history summary and `Security Alerts` section in detailed scan view (`--scan`).
- Configurable alert severity levels via `AlertPolicy` and environment variables (`ALERT_SEVERITY_NEW_OPEN_PORT`, `ALERT_SEVERITY_PORT_CLOSED`, `ALERT_SEVERITY_HOST_DOWN`, `ALERT_SEVERITY_HOST_RECOVERED`), preserving default values and pure deterministic Alert Engine architecture.
- Expected TCP port policy for distinguishing expected and unexpected newly opened ports (`EXPECTED_TCP_PORTS`).
- Dedicated `EXPECTED_OPEN_PORT` and `UNEXPECTED_OPEN_PORT` security alerts with configurable severities (`ALERT_SEVERITY_EXPECTED_OPEN_PORT`, `ALERT_SEVERITY_UNEXPECTED_OPEN_PORT`).



## [Unreleased] — Reliability and security fixes

- Restrict the development PostgreSQL port to loopback and require private passwords.
- Bootstrap a non-admin runtime database role; separate migration credentials.
- Reject non-positive scanner configuration and invalid direct concurrency arguments.
- Reject control characters and malformed scope identifiers in network targets.
- Resolve concurrent host registration without failing an entire monitoring cycle.
- Keep session event counters instead of an unbounded in-memory event history.
- Handle database engine initialization failures within the CLI error boundary.
- Add regression tests and document safe upgrades of existing database volumes.

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - Unreleased

### Added
- `--persist` flag to `netsentinel monitor` to save monitoring cycles to PostgreSQL.
- `MonitoringPersistenceService` to persist atomic snapshots containing the host, scan, port results, and events.
- Persistent monitoring history queries through the `netsentinel history` command.
- Detailed persisted scan inspection including port results and monitoring events via `netsentinel history --scan`.
- Validation of the initial Alembic migration against PostgreSQL.
- PostgreSQL persistence foundation using SQLAlchemy 2.x (async) and asyncpg.
- Declarative ORM models for `hosts`, `scans`, `port_results` and `monitoring_events`.
- Async database engine and session factory (`app/db/session.py`) with lazy initialisation — no connection is opened until explicitly requested.
- Alembic migration infrastructure with async-compatible `migrations/env.py`.
- Initial database migration (`0001_initial_schema`) creating all four tables with correct foreign keys, indexes and constraints.
- `DATABASE_URL` setting in `app/core/config.py` — app continues to function without a database configured.
- Unit tests for ORM metadata, column constraints, enum compatibility, configuration loading and import safety.
- Async `HostRepository` (`app/repositories/host.py`) with `create`, `get_by_id`, `get_by_address`, `list`, and `update` operations.
- `HostAlreadyExistsError` domain exception raised on duplicate-address conflicts.
- Unit tests for `HostRepository` using `AsyncMock` — no database required (`pytest`).
- PostgreSQL integration test suite for `HostRepository` with per-test rollback isolation (`pytest -m integration`).
- Async PostgreSQL persistence for Scan and TCP port results (`ScanRepository`).
- `ScanHostNotFoundError` domain exception for FK violations on scan creation.
- `PortResultInput` dataclass decoupling the repository layer from `app/monitoring/`.
- Unit and integration tests for `ScanRepository` covering create, port results, ordering, listing, limit, and atomicity.
- Asynchronous PostgreSQL persistence for monitoring events (`MonitoringEventRepository`).
- Transactional persistence service for monitoring snapshots and events (`MonitoringPersistenceService`).
- `MonitoringEventRepository` maps `MonitoringEvent` domain objects to `MonitoringEventRecord` ORM rows, preserving original event timestamps.
- Unit and integration tests for `MonitoringEventRepository` covering all event types, timestamp preservation, create_many, ordering, limit, FK violation recovery, and atomicity.

> **Note:** Automatic persistence of monitoring sessions is not enabled yet.
> `netsentinel scan` and `netsentinel monitor` continue to work without a database.

## [0.2.0] - Unreleased

### Added
- Continuous monitoring component (`monitor_host`) via async generator.
- CLI command `netsentinel monitor` to run continuous monitoring with `--interval` and `--count` parameters.
- Snapshot change detection for host availability and TCP port state changes.
- Real-time display of network state changes (Port opened, Port closed, Host became unavailable, Host became available).
- In-memory monitoring session event tracking.
- Monitoring session summary with snapshot and event counts upon exit.

## [0.1.0] - Unreleased

### Added
- Network target validation for IPv4, IPv6 and hostnames.
- Asynchronous TCP connection probe (`TcpProbe`).
- Concurrent TCP port scanner with configurable concurrency limits.
- NetSentinel command-line interface (`netsentinel scan`).
- TCP-based host availability detection and inference.
- Response-time measurement based on TCP handshakes.
- FastAPI `/health` endpoint skeleton.
- Comprehensive unit test suite with mocking and real localhost socket binding.
- Automated static analysis configured with Ruff and mypy.
