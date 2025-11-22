"""
Base models and common fields for Piccolo ORM.
"""
from __future__ import annotations

import datetime

from piccolo import columns, table


class AuditedTable(table.Table, abstract=True):
    """
    Abstract base table with audit fields.

    All tables that track creation and modification should inherit from this.
    """

    created_at = columns.Timestamptz(default=datetime.datetime.now, null=False)
    created_by = columns.Text(null=False)
    last_modified_at = columns.Timestamptz(
        default=datetime.datetime.now,
        auto_update=datetime.datetime.now,
        null=False,
    )
    last_modified_by = columns.Text(null=False)


class SimpleTable(table.Table, abstract=True):
    """
    Abstract base table for simple entities without full audit trail.
    """

    created_at = columns.Timestamptz(default=datetime.datetime.now, null=False)
