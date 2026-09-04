"""Regression coverage for input validation and scanner configuration."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.monitoring.port_scanner import scan_ports
from app.monitoring.target import InvalidTargetError, NetworkTarget, TargetType


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("SCAN_MAX_CONCURRENCY", "0"),
        ("SCAN_MAX_CONCURRENCY", "-1"),
        ("SCAN_TIMEOUT", "0"),
        ("SCAN_TIMEOUT", "-1"),
        ("SCAN_TIMEOUT", "nan"),
        ("SCAN_TIMEOUT", "inf"),
        ("MONITOR_INTERVAL", "0"),
        ("MONITOR_INTERVAL", "-1"),
    ],
)
def test_invalid_settings_fail_at_startup(name, value, monkeypatch):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_shared_dotenv_accepts_compose_only_variables(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "POSTGRES_PASSWORD=test-only\nNETSENTINEL_DB_PASSWORD=test-only\n"
    )
    config = Settings(_env_file=dotenv)
    assert config.SCAN_MAX_CONCURRENCY > 0
    assert "POSTGRES_PASSWORD" not in config.model_dump()


@pytest.mark.parametrize("concurrency", [0, -1])
@pytest.mark.parametrize("ports", [[], [80]])
async def test_invalid_concurrency_fails_without_network(concurrency, ports):
    with patch(
        "app.monitoring.port_scanner.probe_tcp_port", new_callable=AsyncMock
    ) as probe:
        with pytest.raises(ValueError, match="strictly positive"):
            await asyncio.wait_for(
                scan_ports(
                    NetworkTarget.parse("127.0.0.1"), ports, max_concurrency=concurrency
                ),
                timeout=0.2,
            )
        probe.assert_not_awaited()


@pytest.mark.parametrize("concurrency", [True, False, 1.5, "1"])
async def test_concurrency_requires_integer(concurrency):
    with pytest.raises(TypeError, match="integer"):
        await scan_ports(
            NetworkTarget.parse("127.0.0.1"), [80], max_concurrency=concurrency
        )


@pytest.mark.parametrize(
    "control", ["\x1b[2J", "\x00", "\n", "\r", "\t", "\x7f", "\x9b", "\u202e"]
)
@pytest.mark.parametrize("pattern", ["fe80::1%eth0{}", "{}127.0.0.1", "localhost{}"])
def test_targets_reject_controls_before_normalization(control, pattern):
    with pytest.raises(InvalidTargetError, match="control characters"):
        NetworkTarget.parse(pattern.format(control))


@pytest.mark.parametrize("scope", ["12", "eth0", "en0", "veth-test", "eth0.10", "if_1"])
def test_valid_ipv6_scopes_remain_supported(scope):
    target = NetworkTarget.parse(f"fe80::1%{scope}")
    assert target.type == TargetType.IPV6
    assert target.value == f"fe80::1%{scope}"


@pytest.mark.parametrize("scope", ["", "eth/0", "eth[0]", "eth%0", "\u00e9th0"])
def test_invalid_ipv6_scopes_are_rejected(scope):
    with pytest.raises(InvalidTargetError):
        NetworkTarget.parse(f"fe80::1%{scope}")
