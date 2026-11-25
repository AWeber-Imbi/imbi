"""The workflow step types (ADR 0021).

One module per type. A type that is not here fails validation, so a
type is added only when the engine can execute it. The step types of
loaded plugins (ADR 0032) are added by :func:`all_types` and :func:`get`.
"""

import functools
import typing

import pydantic

from imbi.common.plugins import base
from imbi.common.plugins import registry as plugins_registry
from imbi.common.workflows.registry import (
    agent,
    assign_ticket,
    condition,
    deploy,
    email,
    llm_call,
    manual,
    model_decision,
    release,
    rollback,
    schedule,
    script,
    search_logs,
    slack,
    ticket_state_changed,
    wait,
    webhook,
)
from imbi.common.workflows.step_type import StepType

STEP_TYPES: dict[str, StepType] = {
    module.STEP.type: module.STEP
    for module in (
        manual,
        schedule,
        webhook,
        ticket_state_changed,
        wait,
        model_decision,
        llm_call,
        condition,
        script,
        email,
        slack,
        assign_ticket,
        deploy,
        release,
        rollback,
        search_logs,
        agent,
    )
}

#: The fields that a plugin step gets from the host (ADR 0032).
INTEGRATION_SOURCE = 'integration'


def get(step_type: str) -> StepType | None:
    """Return a built-in or plugin step type, else ``None``."""
    if '.' not in step_type:
        return STEP_TYPES.get(step_type)
    return all_types().get(step_type)


def all_types() -> dict[str, StepType]:
    """Return the built-in step types and those of the loaded plugins."""
    types = dict(STEP_TYPES)
    for entry in plugins_registry.list_plugins():
        capability = entry.manifest.get_capability('workflow-steps')
        if capability is not None:
            types.update(
                _plugin_types(
                    entry.manifest.slug,
                    entry.manifest.name,
                    entry.manifest.icon,
                    capability.handler,
                )
            )
    return types


@functools.cache
def _plugin_types(
    slug: str, plugin_label: str, icon: str | None, handler: type
) -> dict[str, StepType]:
    # The registry can reload; the handler class is in the key, so a
    # reloaded plugin builds its types again.
    capability = typing.cast(type[base.WorkflowStepsCapability], handler)
    return {
        f'{slug}.{d.name}': _plugin_type(slug, plugin_label, icon, d)
        for d in capability.steps()
    }


def _plugin_type(
    slug: str,
    plugin_label: str,
    icon: str | None,
    descriptor: base.WorkflowStepDescriptor,
) -> StepType:
    fields: dict[str, typing.Any] = {
        'integration': (
            str,
            pydantic.Field(
                min_length=1,
                description=f'The slug of the {plugin_label} integration.',
                json_schema_extra={
                    'x-imbi-source': INTEGRATION_SOURCE,
                    'x-imbi-plugin': slug,
                },
            ),
        )
    }
    if descriptor.project_scoped:
        fields['project_id'] = (str, pydantic.Field(min_length=1))
    params = pydantic.create_model(
        f'{descriptor.params_model.__name__}WithIntegration',
        __base__=descriptor.params_model,
        **fields,
    )
    permissions = {'integration:read', *descriptor.permissions}
    return StepType(
        type=f'{slug}.{descriptor.name}',
        category=descriptor.category,
        label=f'{plugin_label} · {descriptor.label}',
        description=descriptor.description,
        params=params,
        output=descriptor.output_model,
        sample_output=descriptor.sample_output,
        ports=descriptor.ports,
        side_effect=descriptor.side_effect,
        idempotent=descriptor.idempotent,
        timeout_seconds=descriptor.timeout_seconds,
        retries=descriptor.retries,
        required_permissions=lambda _params: set(permissions),
        plugin=slug,
        icon=icon,
        poll_seconds=descriptor.poll_seconds,
    )


def require(step_type: str) -> StepType:
    """Return a step type that validation has accepted.

    Raises:
        KeyError: The type is unknown, for example because its plugin
            was removed after the workflow was saved.
    """
    found = get(step_type)
    if found is None:
        raise KeyError(step_type)
    return found
