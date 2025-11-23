"""
Namespace model - organizational units for grouping projects.
"""

from __future__ import annotations

from piccolo import columns

from imbi.models import base


class Namespace(base.AuditedTable, tablename="namespaces", schema="v1"):
    """
    Namespace model for organizing projects.

    Namespaces are top-level organizational units (e.g., "platform", "data", "infrastructure").
    """

    id = columns.Serial(primary_key=True)
    namespace_id = columns.Integer(unique=True, null=False, index=True)
    name = columns.Varchar(length=255, unique=True, null=False, index=True)
    slug = columns.Varchar(length=255, unique=True, null=False, index=True)
    icon_class = columns.Text(null=True)  # CSS icon class (e.g., FontAwesome)
    maintained_by = columns.Text(null=True)  # Team or person responsible
    gitlab_group_name = columns.Text(null=True)  # Legacy, will be removed
    aws_ssm_slug = columns.Text(null=True)  # AWS Systems Manager parameter path prefix

    @classmethod
    def ref(cls) -> columns.Varchar:
        """Readable reference for this model."""
        return cls.name
