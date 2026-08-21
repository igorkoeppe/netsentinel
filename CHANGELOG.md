# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
