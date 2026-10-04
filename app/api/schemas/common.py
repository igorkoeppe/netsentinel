"""Common API schemas and models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ErrorDetail(BaseModel):
    """Detailed error object."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., description="Machine-readable error code")
    message: str = Field(..., description="Human-readable error description")


class ErrorResponse(BaseModel):
    """Standardized error envelope."""

    model_config = ConfigDict(extra="forbid")

    error: ErrorDetail


class PaginatedResponse[T](BaseModel):
    """Standard pagination wrapper for list endpoints."""

    model_config = ConfigDict(extra="forbid")

    items: list[T] = Field(..., description="List of items for the current page")
    limit: int = Field(..., description="Maximum items requested")
    offset: int = Field(..., description="Number of items skipped")
    count: int = Field(..., description="Number of items returned in this page")
