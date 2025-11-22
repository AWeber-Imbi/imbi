"""
Project fact models - typed key-value metadata for projects.
"""
from __future__ import annotations

from piccolo.columns import (
    Boolean,
    ForeignKey,
    Integer,
    Numeric,
    Serial,
    Text,
    Varchar,
)

from imbi.models.base import AuditedTable


class FactType(AuditedTable, tablename="fact_types", schema="v1"):
    """
    Fact type model.

    Defines types of facts that can be associated with projects.
    """

    id = Serial(primary_key=True)
    name = Varchar(length=255, unique=True, null=False, index=True)
    fact_type = Text(null=False)  # string, boolean, integer, decimal, date, timestamp
    data_type = Text(null=True)  # UI hint for rendering
    description = Text(null=True)
    ui_options = Text(null=True)  # JSON string for UI configuration
    weight = Integer(default=0, null=False)  # Display order

    @classmethod
    def ref(cls) -> Varchar:
        """Readable reference for this model."""
        return cls.name


class ProjectFact(AuditedTable, tablename="project_facts", schema="v1"):
    """
    Project fact model.

    Stores typed metadata values for projects.
    """

    project_id = ForeignKey("Project", null=False, index=True)
    fact_type_id = ForeignKey("FactType", null=False, index=True)
    value = Text(null=False)  # Stored as text, cast based on fact_type
    score = Numeric(null=True)  # Optional scoring value for this fact

    @classmethod
    def get_unique_keys(cls):
        """Composite unique constraint on project_id + fact_type_id."""
        return [(cls.project_id, cls.fact_type_id)]


class ProjectNote(AuditedTable, tablename="project_notes", schema="v1"):
    """
    Project note model.

    Free-text notes for projects.
    """

    note_id = Serial(primary_key=True)
    project_id = ForeignKey("Project", null=False, index=True)
    note = Text(null=False)

    @classmethod
    def ref(cls) -> Serial:
        """Readable reference for this model."""
        return cls.note_id
