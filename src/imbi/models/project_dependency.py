"""
Project dependency model - tracks dependencies between projects.
"""

from __future__ import annotations

from piccolo import columns
from piccolo.columns.reference import LazyTableReference

from imbi.models import base


class ProjectDependency(
    base.SimpleTable, tablename="project_dependencies", schema="v1"
):
    """
    Project dependency relationship.

    Tracks which projects depend on which other projects.
    """

    project_id = columns.ForeignKey(
        LazyTableReference("Project", module_path="imbi.models.project"),
        null=False,
        index=True,
    )
    dependency_id = columns.ForeignKey(
        LazyTableReference("Project", module_path="imbi.models.project"),
        null=False,
        index=True,
    )
    added_by = columns.Text()

    @classmethod
    def get_unique_keys(cls):
        """Composite unique constraint on project_id + dependency_id."""
        return [(cls.project_id, cls.dependency_id)]
