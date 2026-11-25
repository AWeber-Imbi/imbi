"""The choices of a plugin workflow step form field (ADR 0032).

The workflow builder calls this endpoint to fill a field that has
``x-imbi-choices``. The plugin ``choices`` callable gets the credentials
of the Integration and the params typed so far.
"""

import asyncio
import logging
import typing

import fastapi
import pydantic

from imbi.api.auth import organizations, permissions
from imbi.api.plugins import assignments, lifecycle
from imbi.common import graph
from imbi.common.plugins import base, credentials, errors, registry

LOGGER = logging.getLogger(__name__)

KIND = 'workflow-steps'
MAX_CHOICES = 1000
TIME_LIMIT_SECONDS = 10

_CHOICES = pydantic.TypeAdapter(list[base.Choice])

_QUERY: typing.LiteralString = """
MATCH (i:Integration {{slug: {slug}}})
      -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
RETURN i{{.*}} AS integration
"""

integration_workflow_step_choices_router = fastapi.APIRouter(
    tags=['Workflows'],
    dependencies=[fastapi.Depends(organizations.member_org_id)],
)


class ChoicesRequest(pydantic.BaseModel):
    """The field to load and the params that the editor has so far."""

    field: str
    params: dict[str, typing.Any] = {}


def _not_found(detail: str) -> fastapi.HTTPException:
    return fastapi.HTTPException(status_code=404, detail=detail)


async def _descriptor(
    db: graph.Graph, integration: dict[str, typing.Any], step_name: str
) -> base.WorkflowStepDescriptor:
    """Return the step of the Integration plugin, when it can run."""
    plugin_slug = str(integration.get('plugin') or '')
    off = _not_found('Workflow steps are not enabled for the integration')
    if (
        integration.get('status') == 'inactive'
        or not assignments.capability_state(integration, KIND).get('enabled')
        or not await lifecycle.is_plugin_enabled(db, plugin_slug)
    ):
        raise off
    try:
        capability = registry.get_plugin(plugin_slug).manifest.get_capability(
            KIND
        )
    except errors.PluginNotFoundError:
        capability = None
    if capability is None:
        raise off
    handler = typing.cast(
        type[base.WorkflowStepsCapability], capability.handler
    )
    for descriptor in handler.steps():
        if descriptor.name == step_name:
            return descriptor
    raise _not_found(f'Workflow step {step_name!r} not found')


@integration_workflow_step_choices_router.post(
    '/{integration_slug}/workflow-steps/{step_name}/choices',
    dependencies=[
        fastapi.Depends(permissions.require_permission('integration:read'))
    ],
)
async def list_choices(
    org_slug: str,
    integration_slug: str,
    step_name: str,
    data: ChoicesRequest,
    db: graph.Pool,
    _: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('workflow:write')),
    ],
) -> list[base.Choice]:
    """Return at most 1000 choices for a field of a plugin step.

    Raises:
        400: The field does not have choices.
        404: Integration or step not found, or workflow steps are off.
        502: The plugin failed (``plugin_error``) or did not answer in
            10 seconds (``plugin_timeout``).

    """
    records = await db.execute(
        _QUERY,
        {'slug': integration_slug, 'org_slug': org_slug},
        ['integration'],
    )
    if not records:
        raise _not_found(f'Integration {integration_slug!r} not found')
    integration = assignments.hydrate_integration(
        graph.parse_agtype(records[0]['integration'])
    )
    descriptor = await _descriptor(db, integration, step_name)
    if (
        descriptor.choices is None
        or data.field not in descriptor.choice_fields
    ):
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Field {data.field!r} does not have choices',
        )
    ctx = base.PluginContext(
        project_id='',
        project_slug='',
        org_slug=org_slug,
        integration_slug=integration_slug,
        integration_options=integration.get('options') or {},
        capability_options=assignments.capability_state(integration, KIND).get(
            'options'
        )
        or {},
    )
    secrets = credentials.decrypt_integration_credentials(
        integration.get('encrypted_credentials') or {}
    )
    try:
        async with asyncio.timeout(TIME_LIMIT_SECONDS):
            result = await descriptor.choices(
                ctx, secrets, data.field, data.params
            )
        choices = _CHOICES.validate_python(result)
    except TimeoutError:
        raise fastapi.HTTPException(
            status_code=502, detail={'error': 'plugin_timeout'}
        ) from None
    except Exception:  # The plugin can raise anything.
        LOGGER.exception(
            'Choices of %s.%s failed', integration.get('plugin'), step_name
        )
        raise fastapi.HTTPException(
            status_code=502, detail={'error': 'plugin_error'}
        ) from None
    return choices[:MAX_CHOICES]
