"""
Project Type model - categories/types of projects.
"""

from __future__ import annotations

from piccolo import columns

from imbi.models import base


class ProjectType(base.AuditedTable, tablename="project_types", schema="v1"):
    """
    Project Type model.

    Categorizes projects (e.g., HTTP API, Web Application, Library, etc.)
    """

    id = columns.Serial(primary_key=True)
    name = columns.Varchar(length=255, unique=True, null=False, index=True)
    slug = columns.Varchar(length=255, unique=True, null=False, index=True)
    plural_name = columns.Varchar(length=255, null=False)
    icon_class = columns.Text(null=True)  # CSS icon class
    environment_urls = columns.Boolean(
        default=False, null=False
    )  # Whether this type has environment-specific URLs
    description = columns.Text(null=True)

    @classmethod
    def ref(cls) -> columns.Varchar:
        """Readable reference for this model."""
        return cls.name
