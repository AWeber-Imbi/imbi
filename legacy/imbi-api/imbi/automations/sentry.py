import dataclasses
import typing

from imbi import automations, errors, models
from imbi.clients import sentry


@dataclasses.dataclass
class SentryContext:
    integration_name: str
    project_info: sentry.ProjectInfo


async def create_project(
    context: automations.AutomationContext,
    automation: models.Automation,
    project: models.Project,
) -> None:
    """Create a Sentry project for an Imbi project

    This automation creates a new Sentry project, adds the sentry
    slug as an object identifier, and sets the Sentry link if one
    is configured in settings. The project is initially added to
    the Sentry team associated with the Project namespace.

    The Sentry client retrieves the secret and public client DSNs
    after it creates the project. The public DSN is stored as a
    client secret.

    The sentry project information (as returned by the Sentry
    client) is stored in the context using the function object
    (eg, `create_project`) as the key.

    @see https://docs.sentry.io/api/projects/create-a-new-project/
    @see https://docs.sentry.io/api/projects/list-a-projects-client-keys/

    """
    client = await sentry.create_client(context.application,
                                        automation.integration_name)
    sentry_project = await client.create_project(
        project.namespace.sentry_team_slug or project.namespace.slug,
        project.name)
    context[create_project] = SentryContext(
        integration_name=automation.integration_name,
        project_info=sentry_project)
    context.add_callback(_delete_project)
    context.note_progress('created Sentry project %s for Imbi project %s',
                          sentry_project.slug, project.id)

    # NB -- project is deleted on failure and the deletion is
    # cascaded to the v1.project_secrets, v1.project_identifiers,
    # and v1.project_links tables, so we do not need an explicit cleanup

    key = context.application.encrypt_value(str(sentry_project.keys['public']))
    await context.run_query(
        'INSERT INTO v1.project_secrets(project_id, name, value, created_by)'
        '     VALUES (%(project_id)s, %(key_name)s, %(value)s, %(user)s)', {
            'project_id': project.id,
            'key_name': 'sentry-public-dsn',
            'value': key,
            'user': context.user.username,
        }, 'insert-sentry-keys')
    context.note_progress('stored Public Sentry DSN for Imbi project %s',
                          project.id)

    await context.run_query(
        'INSERT INTO v1.project_identifiers (external_id, integration_name,'
        '                                    project_id, created_by)'
        '     VALUES (%(sentry_id)s, %(integration_name)s, %(project_id)s,'
        '             %(user)s)', {
            'sentry_id': sentry_project.slug,
            'integration_name': automation.integration_name,
            'project_id': project.id,
            'user': context.user.username
        }, 'insert-project-identifiers')
    context.note_progress(
        'registered Sentry identifier %s for Imbi project %s',
        sentry_project.slug, project.id)

    settings = context.application.settings['automations']['sentry']
    if (link_type_id := settings.get('project_link_type_id')) is not None:
        await context.run_query(
            'INSERT INTO v1.project_links (project_id, link_type_id,'
            '                              created_by, url)'
            '     VALUES (%(project_id)s, %(link_type_id)s, %(user)s,'
            '             %(dashboard_url)s)', {
                'project_id': project.id,
                'link_type_id': link_type_id,
                'user': context.user.username,
                'dashboard_url': str(sentry_project.link)
            }, 'insert-project-links')
        context.note_progress('created Sentry link %s for Imbi project %s',
                              sentry_project.link, project.id)


async def _delete_project(context: automations.AutomationContext,
                          _error: BaseException) -> None:
    try:
        sentry_info = typing.cast(SentryContext, context[create_project])
    except KeyError:
        return

    try:
        client = await sentry.create_client(context.application,
                                            sentry_info.integration_name)
    except errors.ClientUnavailableError:
        pass
    else:
        context.note_progress('removing sentry project %s due to error',
                              sentry_info.project_info.slug)
        await client.remove_project(sentry_info.project_info.slug)
