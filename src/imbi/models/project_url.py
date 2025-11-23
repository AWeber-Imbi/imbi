"""
Project URL model - environment-specific URLs for projects.
"""

from __future__ import annotations

from piccolo import columns

import imbi.models.base


class ProjectURL(imbi.models.base.AuditedTable, tablename="project_urls", schema="v1"):
    """
    Project URL model.

    Stores environment-specific URLs for projects (e.g., production URL, staging URL).
    """

    project_id = columns.ForeignKey("Project", null=False, index=True)
    environment = columns.Text(null=False, index=True)  # Environment name
    url = columns.Text(null=False)

    @classmethod
    def get_unique_keys(cls):
        """Composite unique constraint on project_id + environment."""
        return [(cls.project_id, cls.environment)]
