"""
Project model - the central entity in Imbi.

Projects represent services, applications, libraries, and other software components.
"""
from __future__ import annotations

from piccolo import columns

import imbi.models.base


class Project(imbi.models.base.AuditedTable, tablename="projects", schema="v1"):
    """
    Project model.

    The central entity in Imbi representing a service, application, or component.
    """

    id = columns.Serial(primary_key=True)
    namespace_id = columns.ForeignKey("Namespace", null=False, index=True)
    project_type_id = columns.ForeignKey("ProjectType", null=False, index=True)
    name = columns.Varchar(length=255, null=False, index=True)
    slug = columns.Varchar(length=255, null=False, index=True)
    description = columns.Text(null=True)
    environments = columns.Array(columns.Text(), null=True)  # List of environment names
    archived = columns.Boolean(default=False, null=False, index=True)

    # Integration IDs (GitLab removed)
    sentry_project_slug = columns.Text(null=True)
    sonarqube_project_key = columns.Text(null=True)
    pagerduty_service_id = columns.Text(null=True)

    # Configuration management
    configuration_type = columns.Text(null=True)  # e.g., "consul", "etcd", etc.

    @classmethod
    def ref(cls) -> columns.Varchar:
        """Readable reference for this model."""
        return cls.name

    @classmethod
    def get_unique_keys(cls):
        """Composite unique constraints."""
        return [
            (cls.namespace_id, cls.name),
            (cls.namespace_id, cls.slug),
        ]
