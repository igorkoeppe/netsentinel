import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.monitoring.availability import HostAvailabilityResult, HostStatus
from app.monitoring.monitor import monitor_host
from app.monitoring.port_scanner import PortScanResult
from app.monitoring.target import NetworkTarget


@pytest.fixture
def sample_target():
    return NetworkTarget.parse("127.0.0.1")


@pytest.fixture
def mock_snapshot(sample_target):
    return HostAvailabilityResult(
        target=sample_target,
        status=HostStatus.AVAILABLE,
        response_time_ms=10.0,
        scan_result=PortScanResult(
            target=sample_target,
            started_at=MagicMock(),
            finished_at=MagicMock(),
            duration_ms=20.0,
            ports=(),
        ),
    )


@pytest.mark.asyncio
async def test_monitor_host_iterations(sample_target, mock_snapshot):
    """Test that the monitor executes exactly max_iterations times."""
    with patch(
        "app.monitoring.monitor.check_host_availability", new_callable=AsyncMock
    ) as mock_check:
        mock_check.return_value = mock_snapshot

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            snapshots = [
                s
                async for s in monitor_host(
                    target=sample_target, ports=[80], interval=30, max_iterations=3
                )
            ]

            assert len(snapshots) == 3
            assert mock_check.call_count == 3
            # Sleep is called after each iteration, except the last one due to break check
            assert mock_sleep.call_count == 2
            mock_sleep.assert_called_with(30)


@pytest.mark.asyncio
async def test_monitor_host_snapshot_content(sample_target, mock_snapshot):
    """Test that the yielded snapshots match the expected result."""
    with patch(
        "app.monitoring.monitor.check_host_availability", new_callable=AsyncMock
    ) as mock_check:
        mock_check.return_value = mock_snapshot

        with patch("asyncio.sleep", new_callable=AsyncMock):
            snapshots = [
                s
                async for s in monitor_host(
                    target=sample_target, ports=[80], interval=30, max_iterations=1
                )
            ]

            assert len(snapshots) == 1
            assert snapshots[0] == mock_snapshot


@pytest.mark.asyncio
async def test_monitor_host_invalid_interval(sample_target):
    """Test that invalid intervals raise ValueError."""
    for invalid_interval in (0, -1, -30):
        with pytest.raises(ValueError, match="Interval must be strictly positive"):
            # We must iterate or await the generator to trigger the exception
            async for _ in monitor_host(
                target=sample_target, ports=[80], interval=invalid_interval
            ):
                pass


@pytest.mark.asyncio
async def test_monitor_host_scanner_args(sample_target, mock_snapshot):
    """Test that scanner arguments are forwarded correctly."""
    with patch(
        "app.monitoring.monitor.check_host_availability", new_callable=AsyncMock
    ) as mock_check:
        mock_check.return_value = mock_snapshot

        with patch("asyncio.sleep", new_callable=AsyncMock):
            async for _ in monitor_host(
                target=sample_target,
                ports=[22, 80],
                interval=10,
                timeout=5.0,
                max_concurrency=10,
                max_iterations=1,
            ):
                pass

            mock_check.assert_called_once_with(
                target=sample_target,
                ports=[22, 80],
                timeout=5.0,
                max_concurrency=10,
            )


@pytest.mark.asyncio
async def test_monitor_host_cancellation(sample_target, mock_snapshot):
    """Test that cancellation is propagated."""
    with patch(
        "app.monitoring.monitor.check_host_availability", new_callable=AsyncMock
    ) as mock_check:
        mock_check.return_value = mock_snapshot

        # Make sleep raise CancelledError to simulate task cancellation during wait
        with patch(
            "asyncio.sleep", new_callable=AsyncMock, side_effect=asyncio.CancelledError
        ):
            with pytest.raises(asyncio.CancelledError):
                async for _ in monitor_host(
                    target=sample_target, ports=[80], interval=30
                ):
                    pass

            assert mock_check.call_count == 1
