"""
Project model - the central entity in Imbi.

Projects represent services, applications, libraries, and other software components.
"""
from __future__ import annotations

from piccolo.columns import Array, Boolean, ForeignKey, Integer, Serial, Text, Varchar

from imbi.models.base import AuditedTable


class Project(AuditedTable, tablename="projects", schema="v1"):
    """
    Project model.

    The central entity in Imbi representing a service, application, or component.
    """

    id = Serial(primary_key=True)
    namespace_id = ForeignKey("Namespace", null=False, index=True)
    project_type_id = ForeignKey("ProjectType", null=False, index=True)
    name = Varchar(length=255, null=False, index=True)
    slug = Varchar(length=255, null=False, index=True)
    description = Text(null=True)
    environments = Array(Text(), null=True)  # List of environment names
    archived = Boolean(default=False, null=False, index=True)

    # Integration IDs (GitLab removed)
    sentry_project_slug = Text(null=True)
    sonarqube_project_key = Text(null=True)
    pagerduty_service_id = Text(null=True)

    # Configuration management
    configuration_type = Text(null=True)  # e.g., "consul", "etcd", etc.

    @classmethod
    def ref(cls) -> Varchar:
        """Readable reference for this model."""
        return cls.name

    @classmethod
    def get_unique_keys(cls):
        """Composite unique constraints."""
        return [
            (cls.namespace_id, cls.name),
            (cls.namespace_id, cls.slug),
        ]
