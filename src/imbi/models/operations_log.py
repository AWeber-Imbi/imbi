"""
Operations log model - tracks deployments, changes, and incidents.
"""
from __future__ import annotations

from piccolo.columns import ForeignKey, Serial, Text, Timestamptz, Varchar

from imbi.models.base import SimpleTable


class OperationsLog(SimpleTable, tablename="operations_log", schema="v1"):
    """
    Operations log entry model.

    Tracks deployments, changes, incidents, and other operational events.
    """

    id = Serial(primary_key=True)
    recorded_at = Timestamptz(null=False, index=True)  # When entry was created
    recorded_by = Text(null=False)  # Who created the entry
    occurred_at = Timestamptz(null=False, index=True)  # When the event occurred
    completed_at = Timestamptz(null=True)  # When the event completed
    performed_by = Text(null=True)  # Who performed the operation
    project_id = ForeignKey("Project", null=False, index=True)
    environment = Text(null=True)  # Environment where change occurred
    change_type = Text(null=False, index=True)  # deployment, incident, change, etc.
    description = Text(null=False)  # Description of the change
    link = Text(null=True)  # Link to more info (PR, ticket, etc.)
    notes = Text(null=True)  # Additional notes
    ticket_slug = Text(null=True)  # Ticket/issue reference
    version = Text(null=True)  # Version deployed/changed

    @classmethod
    def ref(cls) -> Serial:
        """Readable reference for this model."""
        return cls.id
