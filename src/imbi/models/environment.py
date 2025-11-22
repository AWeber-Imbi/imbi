"""
Environment model - deployment environments (production, staging, etc.)
"""
from __future__ import annotations

from piccolo.columns import Serial, Text, Varchar

from imbi.models.base import AuditedTable


class Environment(AuditedTable, tablename="environments", schema="v1"):
    """
    Environment model.

    Represents deployment environments (production, staging, development, etc.)
    """

    id = Serial(primary_key=True)
    name = Varchar(length=255, unique=True, null=False, index=True)
    icon_class = Text(null=True)  # CSS icon class
    description = Text(null=True)

    @classmethod
    def ref(cls) -> Varchar:
        """Readable reference for this model."""
        return cls.name
