"""Run the workflow steps of plugins (ADR 0032).

The workflows engine does not hold Integration credentials, so it asks
imbi-api to run a plugin step: imbi-api decrypts the credentials of the
Integration that the node selects and calls the step's callable. Each
call is recorded in ``workflow_runtime.plugin_step_calls`` by its
idempotency key, so a repeat of the key gets the first result and makes
no second call.
"""

import asyncio
import logging
import typing

import fastapi
import pydantic

from imbi.api import workflows
from imbi.api.auth import organizations as org_auth
from imbi.api.auth import permissions
from imbi.api.endpoints import _helpers
from imbi.api.plugins import assignments, lifecycle
from imbi.common import graph
from imbi.common import plugins as common_plugins
from imbi.common.plugins import base
from imbi.common.workflows import registry as workflow_steps

LOGGER = logging.getLogger(__name__)

integration_workflow_steps_router = fastapi.APIRouter(
    tags=['Integrations'],
    dependencies=[fastapi.Depends(org_auth.member_org_id)],
)

PERMISSION = 'integration:workflow-step:run'
CAPABILITY = 'workflow-steps'

#: Seconds one call of a plugin step may take at most (ADR 0017).
CALL_TIMEOUT = 60.0
#: A ``running`` call older than this did not finish: a repeat of its
#: idempotency key sets it to ``outcome_unknown``.
STALE_AFTER = CALL_TIMEOUT + 15
#: The largest request and result, in bytes (ADR 0017).
MAX_BYTES = 1024 * 1024

#: The HTTP status and the ``retry`` flag of each error code
#: (``detail={'error': <code>, 'retry': <bool>}``).
CALL_ERRORS: dict[str, tuple[int, bool]] = {
    'call_in_progress': (409, True),
    'outcome_unknown': (409, False),
    'plugin_error': (502, True),
    'plugin_timeout': (504, True),
    'plugin_result_invalid': (502, False),
}


class StepRunRequest(pydantic.BaseModel):
    """One call of a plugin step."""

    #: The step params, without ``integration`` and ``project_id``.
    params: dict[str, typing.Any] = {}
    project_id: str | None = None
    call: base.StepCall
    #: Seconds left in the step. The call gets the lesser of this and
    #: :data:`CALL_TIMEOUT`.
    time_limit_seconds: float | None = pydantic.Field(default=None, gt=0)


def _call_error(code: str) -> fastapi.HTTPException:
    status, retry = CALL_ERRORS[code]
    return fastapi.HTTPException(
        status_code=status, detail={'error': code, 'retry': retry}
    )


def _repeat(row: dict[str, typing.Any]) -> base.StepResult:
    """The answer to a repeat of an idempotency key."""
    match row['status']:
        case 'done':
            return base.StepResult.model_validate(row['result'])
        case 'running':
            raise _call_error('call_in_progress')
        case 'failed':
            raise _call_error(str(row['error']))
        case _:
            raise _call_error('outcome_unknown')


async def load_step(
    db: graph.Graph, org_slug: str, integration_slug: str, step_type: str
) -> tuple[dict[str, typing.Any], base.WorkflowStepDescriptor]:
    """Return the Integration and the step ``<plugin>.<name>`` of its
    plugin, for the run and the choices endpoints.

    The type names its plugin, so a node of one plugin cannot run a step
    of the same name with an Integration of another plugin.

    Raises:
        404: No such active Integration, or its plugin has no such step.
        409: The plugin or its ``workflow-steps`` capability is off.

    """
    # ponytail: loads every Integration of the org (inactive ones
    # excluded) to find one; a single-slug query if orgs get large.
    integrations = await assignments.org_integrations(db, org_slug)
    integration = next(
        (
            i
            for i in integrations.values()
            if i.get('slug') == integration_slug
        ),
        None,
    )
    if integration is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Integration {integration_slug!r} not found',
        )
    plugin_slug = str(integration['plugin'])
    step = workflow_steps.get(step_type)
    if step is None or step.plugin != plugin_slug or step.descriptor is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Plugin {plugin_slug!r} has no workflow step '
            f'{step_type!r}',
        )
    if not (
        assignments.capability_enabled(integration, CAPABILITY)
        and await lifecycle.is_plugin_enabled(db, plugin_slug)
    ):
        raise fastapi.HTTPException(
            status_code=409,
            detail=(
                f'The {CAPABILITY} capability of {integration_slug!r} '
                'is not enabled'
            ),
        )
    return integration, step.descriptor


def plugin_args(
    integration: dict[str, typing.Any],
    org_slug: str,
    project_id: str = '',
    project_slug: str = '',
    team_slug: str | None = None,
) -> tuple[base.PluginContext, dict[str, str]]:
    """Return the context and the decrypted credentials of a call."""
    options: dict[str, typing.Any] = (
        assignments.capability_state(integration, CAPABILITY).get('options')
        or {}
    )
    ctx = base.PluginContext(
        project_id=project_id,
        project_slug=project_slug,
        org_slug=org_slug,
        team_slug=team_slug,
        integration_slug=str(integration['slug']),
        integration_options=integration.get('options') or {},
        capability_options=options,
        assignment_options=options,
    )
    return ctx, common_plugins.decrypt_integration_credentials(
        integration.get('encrypted_credentials') or {}
    )


def _result(
    descriptor: base.WorkflowStepDescriptor, result: object
) -> base.StepResult:
    """Check what the plugin returned. Raise ``plugin_result_invalid``."""
    if not isinstance(result, base.StepResult):
        raise _call_error('plugin_result_invalid')
    if result.poll:
        if descriptor.poll_seconds is None:
            raise _call_error('plugin_result_invalid')
        checked = base.StepResult(poll=True, state=result.state)
    else:
        if result.port not in descriptor.ports:
            raise _call_error('plugin_result_invalid')
        try:
            output = descriptor.output_model.model_validate(result.output)
        except pydantic.ValidationError:
            raise _call_error('plugin_result_invalid') from None
        checked = base.StepResult(
            output=output.model_dump(mode='json'), port=result.port
        )
    if len(checked.model_dump_json().encode()) > MAX_BYTES:
        raise _call_error('plugin_result_invalid')
    return checked


@integration_workflow_steps_router.post(
    '/{step_type}/run', response_model=base.StepResult
)
async def run_workflow_step(
    org_slug: str,
    integration_slug: str,
    step_type: str,
    data: StepRunRequest,
    db: graph.Pool,
    calls: workflows.PluginCalls,
    org_id: org_auth.MemberOrgId,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission(PERMISSION)),
    ],
    idempotency_key: typing.Annotated[
        str,
        fastapi.Header(alias='Idempotency-Key', min_length=1, max_length=200),
    ],
) -> base.StepResult:
    """Run one call of a plugin workflow step with the credentials of
    the Integration.

    Only the ``imbi-workflows`` service account holds the permission.
    The ``Idempotency-Key`` is ``<run_id>:<node_id>:<attempt>:<poll>``:
    a repeat of the key gets the result of the first call. An error of
    the call has ``detail={'error': <code>, 'retry': <bool>}`` (see
    :data:`CALL_ERRORS`).

    Raises:
        403: No permission, or not a member of the organization.
        404: No such Integration, step of its plugin, or project.
        409: The plugin or its ``workflow-steps`` capability is off, a
            call with the key is still running (``call_in_progress``),
            or one did not finish (``outcome_unknown``).
        413: The request is larger than 1 MiB.
        422: The params are not valid, or a project-scoped step has no
            ``project_id``.
        502: The plugin failed or returned a result that is not valid.
        504: The plugin did not answer in time.

    """
    if len(data.model_dump_json().encode()) > MAX_BYTES:
        raise fastapi.HTTPException(
            status_code=413, detail='The request is larger than 1 MiB'
        )
    integration, descriptor = await load_step(
        db, org_slug, integration_slug, step_type
    )
    project_slug, team_slug = '', None
    if data.project_id is not None:
        await org_auth.member_project_org_id(
            org_slug, data.project_id, db, org_id
        )
        project_slug, team_slug = await _helpers.lookup_project_slugs(
            db, data.project_id
        )
    elif descriptor.project_scoped:
        raise fastapi.HTTPException(
            status_code=422, detail='The step needs a project_id'
        )
    try:
        params = descriptor.params_model.model_validate(data.params)
    except pydantic.ValidationError as e:
        raise fastapi.HTTPException(
            status_code=422,
            detail=e.errors(include_input=False, include_url=False),
        ) from e
    row, new = await calls.start(
        {
            'organization_id': org_id,
            'principal': auth.principal_name,
            'idempotency_key': idempotency_key,
            'run_id': data.call.run_id,
            'integration_slug': integration_slug,
            'step_type': step_type,
        },
        STALE_AFTER,
    )
    if not new:
        return _repeat(row)
    ctx, credentials = plugin_args(
        integration, org_slug, data.project_id or '', project_slug, team_slug
    )
    limit = min(CALL_TIMEOUT, data.time_limit_seconds or CALL_TIMEOUT)
    try:
        async with asyncio.timeout(limit):
            answer = await descriptor.callable(
                ctx, credentials, params, data.call
            )
    except TimeoutError:
        await calls.finish(row['id'], error='plugin_timeout')
        raise _call_error('plugin_timeout') from None
    except Exception:
        LOGGER.exception('Plugin step %s failed', step_type)
        await calls.finish(row['id'], error='plugin_error')
        raise _call_error('plugin_error') from None
    try:
        result = _result(descriptor, answer)
    except fastapi.HTTPException:
        await calls.finish(row['id'], error='plugin_result_invalid')
        raise
    await calls.finish(row['id'], result=result.model_dump(mode='json'))
    return result


#: The most choices that a choices call returns.
MAX_CHOICES = 1000
#: Seconds that a choices call may take at most.
CHOICES_TIMEOUT = 10

_CHOICES = pydantic.TypeAdapter(list[base.Choice])


class ChoicesRequest(pydantic.BaseModel):
    """The field to load and the params that the editor has so far."""

    field: str
    params: dict[str, typing.Any] = {}


@integration_workflow_steps_router.post(
    '/{step_type}/choices',
    dependencies=[
        fastapi.Depends(permissions.require_permission('integration:read'))
    ],
)
async def list_choices(
    org_slug: str,
    integration_slug: str,
    step_type: str,
    data: ChoicesRequest,
    db: graph.Pool,
    _: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('workflow:write')),
    ],
) -> list[base.Choice]:
    """Return at most 1000 choices for a field of a plugin step.

    The workflow builder calls this to fill a field that has
    ``x-imbi-choices``. ``params`` are the values typed so far.

    Raises:
        400: The field does not have choices.
        404: No such Integration, or its plugin has no such step.
        409: The plugin or its ``workflow-steps`` capability is off.
        502: The plugin failed (``plugin_error``) or did not answer in
            10 seconds (``plugin_timeout``).

    """
    integration, descriptor = await load_step(
        db, org_slug, integration_slug, step_type
    )
    if (
        descriptor.choices is None
        or data.field not in descriptor.choice_fields
    ):
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Field {data.field!r} does not have choices',
        )
    ctx, credentials = plugin_args(integration, org_slug)
    try:
        async with asyncio.timeout(CHOICES_TIMEOUT):
            result = await descriptor.choices(
                ctx, credentials, data.field, data.params
            )
        choices = _CHOICES.validate_python(result)
    except TimeoutError:
        raise fastapi.HTTPException(
            status_code=502, detail={'error': 'plugin_timeout'}
        ) from None
    except Exception:  # The plugin can raise anything.
        LOGGER.exception('Choices of %s failed', step_type)
        raise fastapi.HTTPException(
            status_code=502, detail={'error': 'plugin_error'}
        ) from None
    return choices[:MAX_CHOICES]
