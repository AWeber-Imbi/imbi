"""
Namespace model - organizational units for grouping projects.
"""
from __future__ import annotations

from piccolo.columns import Integer, Serial, Text, Varchar
from piccolo.table import Table

from imbi.models.base import AuditedTable


class Namespace(AuditedTable, tablename="namespaces", schema="v1"):
    """
    Namespace model for organizing projects.

    Namespaces are top-level organizational units (e.g., "platform", "data", "infrastructure").
    """

    id = Serial(primary_key=True)
    namespace_id = Integer(unique=True, null=False, index=True)
    name = Varchar(length=255, unique=True, null=False, index=True)
    slug = Varchar(length=255, unique=True, null=False, index=True)
    icon_class = Text(null=True)  # CSS icon class (e.g., FontAwesome)
    maintained_by = Text(null=True)  # Team or person responsible
    gitlab_group_name = Text(null=True)  # Legacy, will be removed
    aws_ssm_slug = Text(null=True)  # AWS Systems Manager parameter path prefix

    @classmethod
    def ref(cls) -> Varchar:
        """Readable reference for this model."""
        return cls.name
