"""
Project link models - external links for projects (GitHub, docs, etc.)
"""
from __future__ import annotations

from piccolo.columns import ForeignKey, Serial, Text, Varchar

from imbi.models.base import AuditedTable


class ProjectLinkType(AuditedTable, tablename="project_link_types", schema="v1"):
    """
    Project link type model.

    Defines types of links (e.g., GitHub, Documentation, Dashboard).
    """

    id = Serial(primary_key=True)
    link_type = Varchar(length=255, unique=True, null=False, index=True)
    icon_class = Text(null=True)  # CSS icon class

    @classmethod
    def ref(cls) -> Varchar:
        """Readable reference for this model."""
        return cls.link_type


class ProjectLink(AuditedTable, tablename="project_links", schema="v1"):
    """
    Project link model.

    Links to external resources for a project.
    """

    project_id = ForeignKey("Project", null=False, index=True)
    link_type_id = ForeignKey("ProjectLinkType", null=False, index=True)
    url = Text(null=False)

    @classmethod
    def get_unique_keys(cls):
        """Composite unique constraint on project_id + link_type_id."""
        return [(cls.project_id, cls.link_type_id)]
