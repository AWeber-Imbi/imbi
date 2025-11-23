"""
Project link models - external links for projects (GitHub, docs, etc.)
"""

from __future__ import annotations

from piccolo import columns
from piccolo.columns.reference import LazyTableReference

from imbi.models import base


class ProjectLinkType(base.AuditedTable, tablename="project_link_types", schema="v1"):
    """
    Project link type model.

    Defines types of links (e.g., GitHub, Documentation, Dashboard).
    """

    id = columns.Serial(primary_key=True)
    link_type = columns.Varchar(length=255, unique=True, null=False, index=True)
    icon_class = columns.Text(null=True)  # CSS icon class

    @classmethod
    def ref(cls) -> columns.Varchar:
        """Readable reference for this model."""
        return cls.link_type


class ProjectLink(base.AuditedTable, tablename="project_links", schema="v1"):
    """
    Project link model.

    Links to external resources for a project.
    """

    project_id = columns.ForeignKey(
        LazyTableReference("Project", module_path="imbi.models.project"),
        null=False,
        index=True,
    )
    link_type_id = columns.ForeignKey(
        LazyTableReference("ProjectLinkType", module_path="imbi.models.project_link"),
        null=False,
        index=True,
    )
    url = columns.Text(null=False)

    @classmethod
    def get_unique_keys(cls):
        """Composite unique constraint on project_id + link_type_id."""
        return [(cls.project_id, cls.link_type_id)]
