"""Pydantic models declared by the AWS plugin and exposed via the
plugin's manifest as plugin-declared graph types.
"""

import re
import typing

import pydantic

_ACCOUNT_ID_RE = re.compile(r'^\d{12}$')


class AwsAccount(pydantic.BaseModel):
    """An AWS account record managed by operators.

    Referenced by the ``aws-iam-ic`` plugin manifest's
    ``vertex_labels[0].model_ref``.  Core auto-mounts CRUD endpoints
    under
    ``/admin/plugins/{plugin_id}/entities/AwsAccount`` from this model
    via the plugin-declared schemas surface.
    """

    id: str
    account_id: typing.Annotated[str, pydantic.Field(pattern=r'^\d{12}$')]
    name: str
    default_role_name: str | None = None
    default_region: str | None = None
    tags: dict[str, str] = pydantic.Field(default_factory=dict)

    @pydantic.field_validator('account_id')
    @classmethod
    def _validate_account_id(cls, value: str) -> str:
        if not _ACCOUNT_ID_RE.match(value):
            raise ValueError('AWS account_id must be a 12-digit string')
        return value
