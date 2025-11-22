"""
Project dependency model - tracks dependencies between projects.
"""
from __future__ import annotations

from piccolo.columns import ForeignKey, Text

from imbi.models.base import SimpleTable


class ProjectDependency(SimpleTable, tablename="project_dependencies", schema="v1"):
    """
    Project dependency relationship.

    Tracks which projects depend on which other projects.
    """

    project_id = ForeignKey("Project", null=False, index=True)
    dependency_id = ForeignKey("Project", null=False, index=True)
    added_by = Text()

    @classmethod
    def get_unique_keys(cls):
        """Composite unique constraint on project_id + dependency_id."""
        return [(cls.project_id, cls.dependency_id)]
