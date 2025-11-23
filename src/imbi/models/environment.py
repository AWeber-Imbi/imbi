"""
Environment model - deployment environments (production, staging, etc.)
"""

from __future__ import annotations

from piccolo import columns

import imbi.models.base


class Environment(imbi.models.base.AuditedTable, tablename="environments", schema="v1"):
    """
    Environment model.

    Represents deployment environments (production, staging, development, etc.)
    """

    id = columns.Serial(primary_key=True)
    name = columns.Varchar(length=255, unique=True, null=False, index=True)
    icon_class = columns.Text(null=True)  # CSS icon class
    description = columns.Text(null=True)

    @classmethod
    def ref(cls) -> columns.Varchar:
        """Readable reference for this model."""
        return cls.name
