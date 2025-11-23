"""
Project fact models - typed key-value metadata for projects.
"""

from __future__ import annotations

from piccolo import columns
from piccolo.columns.reference import LazyTableReference

from imbi.models import base


class FactType(base.AuditedTable, tablename="fact_types", schema="v1"):
    """
    Fact type model.

    Defines types of facts that can be associated with projects.
    """

    id = columns.Serial(primary_key=True)
    name = columns.Varchar(length=255, unique=True, null=False, index=True)
    fact_type = columns.Text(
        null=False
    )  # string, boolean, integer, decimal, date, timestamp
    data_type = columns.Text(null=True)  # UI hint for rendering
    description = columns.Text(null=True)
    ui_options = columns.Text(null=True)  # JSON string for UI configuration
    weight = columns.Integer(default=0, null=False)  # Display order

    @classmethod
    def ref(cls) -> columns.Varchar:
        """Readable reference for this model."""
        return cls.name


class ProjectFact(base.AuditedTable, tablename="project_facts", schema="v1"):
    """
    Project fact model.

    Stores typed metadata values for projects.
    """

    project_id = columns.ForeignKey(
        LazyTableReference("Project", module_path="imbi.models.project"),
        null=False,
        index=True,
    )
    fact_type_id = columns.ForeignKey(
        LazyTableReference("FactType", module_path="imbi.models.project_fact"),
        null=False,
        index=True,
    )
    value = columns.Text(null=False)  # Stored as text, cast based on fact_type
    score = columns.Numeric(null=True)  # Optional scoring value for this fact

    @classmethod
    def get_unique_keys(cls):
        """Composite unique constraint on project_id + fact_type_id."""
        return [(cls.project_id, cls.fact_type_id)]


class ProjectNote(base.AuditedTable, tablename="project_notes", schema="v1"):
    """
    Project note model.

    Free-text notes for projects.
    """

    # Piccolo automatically adds 'id' as primary key from AuditedTable
    # So we don't need note_id - just use id
    project_id = columns.ForeignKey(
        LazyTableReference("Project", module_path="imbi.models.project"),
        null=False,
        index=True,
    )
    note = columns.Text(null=False)

    @classmethod
    def ref(cls) -> columns.Serial:
        """Readable reference for this model."""
        return cls.id
