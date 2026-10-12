"""Rollback: deploy an earlier version of a project again."""

import typing

import pydantic

from imbi.common.workflows import step_type
from imbi.common.workflows.registry import deploy


class Params(pydantic.BaseModel):
    project_id: str = pydantic.Field(min_length=1)
    environment: str = pydantic.Field(min_length=1)
    target: typing.Literal['last_healthy', 'previous', 'version'] = (
        'last_healthy'
    )
    version: str | None = pydantic.Field(
        default=None, description='Required when target is version.'
    )

    @pydantic.model_validator(mode='after')
    def _version_for_target(self) -> typing.Self:
        if self.target == 'version' and not self.version:
            raise ValueError('version is required when target is version')
        return self


STEP = step_type.StepType(
    type='rollback',
    category='action',
    label='Rollback',
    description='Deploys an earlier version of a project again.',
    params=Params,
    output=deploy.Output,
    sample_output={'deployment_id': 'sample', 'status': 'success'},
    side_effect=True,
    required_permissions=deploy.required_permissions,
)
