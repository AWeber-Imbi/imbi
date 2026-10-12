"""Deploy: deploy a version of a project to an environment."""

import typing

import pydantic

from imbi.common.workflows import step_type


class Params(pydantic.BaseModel):
    project_id: str = pydantic.Field(min_length=1)
    environment: str = pydantic.Field(min_length=1)
    version: str = pydantic.Field(min_length=1)


class Output(pydantic.BaseModel):
    deployment_id: str
    status: str


def required_permissions(_params: dict[str, typing.Any]) -> set[str]:
    return {'project:deployment:write'}


STEP = step_type.StepType(
    type='deploy',
    category='action',
    label='Deploy',
    description='Deploys a version of a project to an environment.',
    params=Params,
    output=Output,
    sample_output={'deployment_id': 'sample', 'status': 'success'},
    ports=('Succeeded', 'Failed'),
    side_effect=True,
    required_permissions=required_permissions,
)
