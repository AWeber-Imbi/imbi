"""
Project URL model - environment-specific URLs for projects.
"""
from __future__ import annotations

from piccolo.columns import ForeignKey, Text

from imbi.models.base import AuditedTable


class ProjectURL(AuditedTable, tablename="project_urls", schema="v1"):
    """
    Project URL model.

    Stores environment-specific URLs for projects (e.g., production URL, staging URL).
    """

    project_id = ForeignKey("Project", null=False, index=True)
    environment = Text(null=False, index=True)  # Environment name
    url = Text(null=False)

    @classmethod
    def get_unique_keys(cls):
        """Composite unique constraint on project_id + environment."""
        return [(cls.project_id, cls.environment)]
