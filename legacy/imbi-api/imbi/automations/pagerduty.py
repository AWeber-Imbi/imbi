import dataclasses
import typing

from imbi import automations, errors, models
from imbi.clients import pagerduty


@dataclasses.dataclass
class PagerDutyContext:
    integration_name: str
    service_info: pagerduty.ServiceInfo


async def create_service(
    context: automations.AutomationContext,
    automation: models.Automation,
    project: models.Project,
) -> None:
    """Create a PagerDuty service for an Imbi project

    This automation creates a new PagerDuty service using the same
    name as `project` and attaching it to the escalation policy
    associated with the namespace. The generated service ID is saved
    as a pagerduty project identifier. A link to the dashboard is
    added to the project if the `automations/pagerduty/project_link_type_id`
    configuration value is set.

    The PagerDuty service information is saved in the context using
    the function object (eg, `create_service`) as the key.

    @see https://developer.pagerduty.com/api-reference/7062f2631b397-create-a-service
    """  # noqa: E501 -- line too long
    if project.namespace.pagerduty_policy is None:
        context.note_progress('not enabled for namespace %s, skipping',
                              project.namespace.name)
        return

    client = await pagerduty.create_client(context.application,
                                           automation.integration_name)
    service = await client.create_service(project)
    context[create_service] = PagerDutyContext(
        integration_name=automation.integration_name, service_info=service)
    context.add_callback(_delete_project)

    # NB -- the integration is a child resource of the service, so it
    # will be deleted when we delete the service, extra cleanup not required
    hook = await client.create_inbound_api_integration(
        'pagerduty-inbound-events', service)
    key = context.application.encrypt_value(hook.integration_key)
    await context.run_query(
        'INSERT INTO v1.project_secrets(project_id, name, value, created_by)'
        '     VALUES (%(project_id)s, %(key_name)s, %(value)s, %(user)s)', {
            'project_id': project.id,
            'key_name': 'pagerduty-integration-key',
            'value': key,
            'user': context.user.username,
        }, 'insert-pagerduty-keys')

    # NB -- the DB fields are cascade deleted when the project is deleted,
    # so extra cleanup is not required
    await context.run_query(
        'INSERT INTO v1.project_identifiers (external_id, integration_name,'
        '                                    project_id, created_by)'
        '     VALUES (%(pagerduty_id)s, %(integration_name)s, %(project_id)s,'
        '             %(user)s)', {
            'pagerduty_id': service.id,
            'integration_name': automation.integration_name,
            'project_id': project.id,
            'user': context.user.username,
        }, 'insert-project-identifiers')
    context.note_progress(
        'registered PagerDuty service %s for Imbi project %s', service.id,
        project.id)

    settings = context.application.settings['automations']['pagerduty']
    if (link_type_id := settings.get('project_link_type_id')) is not None:
        await context.run_query(
            'INSERT INTO v1.project_links (project_id, link_type_id,'
            '                              created_by, url)'
            '     VALUES (%(project_id)s, %(link_type_id)s, %(user)s,'
            '             %(url)s)', {
                'project_id': project.id,
                'link_type_id': link_type_id,
                'user': context.user.username,
                'url': str(service.html_url),
            }, 'insert-project-links')
        context.note_progress('created PagerDuty link %s for Imbi project %s',
                              service.html_url, project.id)


async def _delete_project(context: automations.AutomationContext,
                          _error: BaseException) -> None:
    try:
        pd_info = typing.cast(PagerDutyContext, context[create_service])
    except KeyError:
        return

    try:
        client = await pagerduty.create_client(context.application,
                                               pd_info.integration_name)
    except errors.ClientUnavailableError:
        pass
    else:
        context.note_progress('removing PagerDuty service %s due to error',
                              pd_info.service_info.id)
        await client.remove_service(pd_info.service_info.id)
