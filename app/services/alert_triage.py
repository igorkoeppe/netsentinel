"""AlertTriageService — application service for security alert triage.

Orchestrates reading persisted alerts, validating and executing domain lifecycle
transitions (acknowledge, resolve), persisting updates, and managing database
transaction boundaries (commit/rollback).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.detection.alerts import acknowledge_alert, resolve_alert
from app.repositories.alert import AlertRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.security_alert import SecurityAlertRecord

logger = logging.getLogger(__name__)


def _to_comparable_dt(dt: datetime) -> datetime:
    """Normalize datetime for offset-naive vs offset-aware comparison."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


class AlertTriageError(Exception):
    """Base exception for alert triage application service operations."""


class AlertNotFoundError(AlertTriageError):
    """Raised when a requested security alert does not exist."""

    def __init__(self, alert_id: int) -> None:
        self.alert_id = alert_id
        super().__init__(f"Security alert with id={alert_id} was not found.")


class AlertTriageService:
    """Application service for managing the triage lifecycle of security alerts.

    Parameters
    ----------
    session:
        An open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.
    alert_repo:
        Optional :class:`~app.repositories.alert.AlertRepository` instance.
        If omitted, one will be instantiated with ``session``.
    """

    def __init__(
        self,
        session: AsyncSession,
        alert_repo: AlertRepository | None = None,
    ) -> None:
        self._session = session
        self._alert_repo = alert_repo or AlertRepository(session)

    async def get_alert(self, alert_id: int) -> SecurityAlertRecord:
        """Fetch a persisted security alert by its primary key.

        Parameters
        ----------
        alert_id:
            Primary key of the security alert.

        Returns
        -------
        SecurityAlertRecord
            The persisted security alert record.

        Raises
        ------
        AlertNotFoundError
            If no alert with ``alert_id`` exists.
        """
        record = await self._alert_repo.get_by_id(alert_id)
        if record is None:
            raise AlertNotFoundError(alert_id)
        return record

    async def acknowledge(
        self,
        alert_id: int,
        *,
        at: datetime | None = None,
    ) -> SecurityAlertRecord:
        """Acknowledge a persisted security alert.

        Transitions the alert's lifecycle from OPEN to ACKNOWLEDGED, recording
        the acknowledgment timestamp and committing the transaction.

        Flow:
        1. Fetch the alert record by ID.
        2. Validate transition timestamp against alert creation timestamp.
        3. Reconstruct domain AlertLifecycle and execute domain acknowledge.
        4. Update lifecycle columns in the repository.
        5. Commit the transaction.

        Parameters
        ----------
        alert_id:
            Primary key of the security alert to acknowledge.
        at:
            Optional transition timestamp. Defaults to UTC now if omitted.

        Returns
        -------
        SecurityAlertRecord
            The updated security alert record.

        Raises
        ------
        AlertNotFoundError
            If no alert with ``alert_id`` exists.
        InvalidAlertStateTransitionError
            If the transition is not allowed from the current status.
        ValueError
            If the transition timestamp violates chronological constraints.
        Exception
            Any database or execution error encountered during the operation.
            The transaction is safely rolled back before propagating.
        """
        try:
            record = await self._alert_repo.get_by_id(alert_id)
            if record is None:
                raise AlertNotFoundError(alert_id)

            if at is not None and _to_comparable_dt(at) < _to_comparable_dt(
                record.created_at
            ):
                raise ValueError(
                    f"acknowledged_at ({at}) cannot be earlier "
                    f"than alert timestamp ({record.created_at})."
                )

            current_lifecycle = record.to_lifecycle()
            new_lifecycle = acknowledge_alert(current_lifecycle, at=at)

            updated = await self._alert_repo.update_lifecycle(alert_id, new_lifecycle)
            if updated is None:
                raise AlertNotFoundError(alert_id)

            await self._session.commit()
            logger.info(
                "Security alert acknowledged: id=%s acknowledged_at=%s",
                alert_id,
                updated.acknowledged_at,
            )
            return updated
        except Exception as exc:
            logger.error("Failed to acknowledge alert id=%s: %s", alert_id, exc)
            await self._session.rollback()
            raise

    async def resolve(
        self,
        alert_id: int,
        *,
        at: datetime | None = None,
    ) -> SecurityAlertRecord:
        """Resolve a persisted security alert.

        Transitions the alert's lifecycle from OPEN or ACKNOWLEDGED to RESOLVED,
        recording the resolution timestamp and committing the transaction.

        Flow:
        1. Fetch the alert record by ID.
        2. Validate transition timestamp against alert creation timestamp.
        3. Reconstruct domain AlertLifecycle and execute domain resolve.
        4. Update lifecycle columns in the repository.
        5. Commit the transaction.

        Parameters
        ----------
        alert_id:
            Primary key of the security alert to resolve.
        at:
            Optional transition timestamp. Defaults to UTC now if omitted.

        Returns
        -------
        SecurityAlertRecord
            The updated security alert record.

        Raises
        ------
        AlertNotFoundError
            If no alert with ``alert_id`` exists.
        InvalidAlertStateTransitionError
            If the transition is not allowed from the current status.
        ValueError
            If the transition timestamp violates chronological constraints.
        Exception
            Any database or execution error encountered during the operation.
            The transaction is safely rolled back before propagating.
        """
        try:
            record = await self._alert_repo.get_by_id(alert_id)
            if record is None:
                raise AlertNotFoundError(alert_id)

            if at is not None and _to_comparable_dt(at) < _to_comparable_dt(
                record.created_at
            ):
                raise ValueError(
                    f"resolved_at ({at}) cannot be earlier "
                    f"than alert timestamp ({record.created_at})."
                )

            current_lifecycle = record.to_lifecycle()
            new_lifecycle = resolve_alert(current_lifecycle, at=at)

            updated = await self._alert_repo.update_lifecycle(alert_id, new_lifecycle)
            if updated is None:
                raise AlertNotFoundError(alert_id)

            await self._session.commit()
            logger.info(
                "Security alert resolved: id=%s resolved_at=%s",
                alert_id,
                updated.resolved_at,
            )
            return updated
        except Exception as exc:
            logger.error("Failed to resolve alert id=%s: %s", alert_id, exc)
            await self._session.rollback()
            raise
