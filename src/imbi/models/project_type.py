"""
Project Type model - categories/types of projects.
"""
from __future__ import annotations

from piccolo.columns import Boolean, Serial, Text, Varchar

from imbi.models.base import AuditedTable


class ProjectType(AuditedTable, tablename="project_types", schema="v1"):
    """
    Project Type model.

    Categorizes projects (e.g., HTTP API, Web Application, Library, etc.)
    """

    id = Serial(primary_key=True)
    name = Varchar(length=255, unique=True, null=False, index=True)
    slug = Varchar(length=255, unique=True, null=False, index=True)
    plural_name = Varchar(length=255, null=False)
    icon_class = Text(null=True)  # CSS icon class
    environment_urls = Boolean(default=False, null=False)  # Whether this type has environment-specific URLs
    description = Text(null=True)

    @classmethod
    def ref(cls) -> Varchar:
        """Readable reference for this model."""
        return cls.name
