"""
Base models and common fields for Piccolo ORM.
"""
from __future__ import annotations

from datetime import datetime

from piccolo.columns import Text, Timestamptz
from piccolo.table import Table


class AuditedTable(Table, abstract=True):
    """
    Abstract base table with audit fields.

    All tables that track creation and modification should inherit from this.
    """

    created_at = Timestamptz(default=datetime.now, null=False)
    created_by = Text(null=False)
    last_modified_at = Timestamptz(
        default=datetime.now,
        auto_update=datetime.now,
        null=False,
    )
    last_modified_by = Text(null=False)


class SimpleTable(Table, abstract=True):
    """
    Abstract base table for simple entities without full audit trail.
    """

    created_at = Timestamptz(default=datetime.now, null=False)
