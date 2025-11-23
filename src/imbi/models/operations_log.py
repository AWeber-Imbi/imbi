"""
Operations log model - tracks deployments, changes, and incidents.
"""

from __future__ import annotations

from piccolo import columns

import imbi.models.base


class OperationsLog(
    imbi.models.base.SimpleTable, tablename="operations_log", schema="v1"
):
    """
    Operations log entry model.

    Tracks deployments, changes, incidents, and other operational events.
    """

    id = columns.Serial(primary_key=True)
    recorded_at = columns.Timestamptz(null=False, index=True)  # When entry was created
    recorded_by = columns.Text(null=False)  # Who created the entry
    occurred_at = columns.Timestamptz(null=False, index=True)  # When the event occurred
    completed_at = columns.Timestamptz(null=True)  # When the event completed
    performed_by = columns.Text(null=True)  # Who performed the operation
    project_id = columns.ForeignKey("Project", null=False, index=True)
    environment = columns.Text(null=True)  # Environment where change occurred
    change_type = columns.Text(
        null=False, index=True
    )  # deployment, incident, change, etc.
    description = columns.Text(null=False)  # Description of the change
    link = columns.Text(null=True)  # Link to more info (PR, ticket, etc.)
    notes = columns.Text(null=True)  # Additional notes
    ticket_slug = columns.Text(null=True)  # Ticket/issue reference
    version = columns.Text(null=True)  # Version deployed/changed

    @classmethod
    def ref(cls) -> columns.Serial:
        """Readable reference for this model."""
        return cls.id
