"""Release: cut a new tag at a commit and promote it, as the UI does."""

import pydantic

from imbi.common.workflows import step_type
from imbi.common.workflows.registry import deploy


class Params(pydantic.BaseModel):
    project_id: str = pydantic.Field(min_length=1)
    from_environment: str = pydantic.Field(
        min_length=1, description='The environment that runs the commit.'
    )
    environment: str = pydantic.Field(
        min_length=1, description='The environment to release to.'
    )
    commit: str = pydantic.Field(min_length=1)
    tag: str = pydantic.Field(
        default='',
        description='Empty: drafted from the commits that the environment '
        'does not run yet.',
    )
    release_notes: str = pydantic.Field(
        default='', description='Markdown. Empty: drafted with the tag.'
    )


class Output(pydantic.BaseModel):
    deployment_id: str
    status: str
    tag: str | None
    release_notes: str
    #: The draft was made without the model.
    degraded: bool
    error: str | None


STEP = step_type.StepType(
    type='release',
    category='action',
    label='Release',
    description=(
        'Cuts a new tag at a commit and promotes it to an environment, then '
        'waits for the build and the rollout.'
    ),
    params=Params,
    output=Output,
    sample_output={
        'deployment_id': 'sample',
        'status': 'success',
        'tag': '1.4.0',
        'release_notes': '- Add things',
        'degraded': False,
        'error': None,
    },
    ports=('Succeeded', 'Failed'),
    side_effect=True,
    timeout_seconds=3600,
    retries=2,
    required_permissions=deploy.required_permissions,
)
