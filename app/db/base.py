"""Declarative base for all ORM models.

All models must inherit from ``Base`` so that Alembic can discover
the full metadata when generating migrations.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base for all SQLAlchemy ORM models."""
