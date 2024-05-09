import dataclasses
import typing

from imbi import automations, errors, models
from imbi.clients import sonarqube


@dataclasses.dataclass
class SonarQubeContext:
    integration_name: str
    project_info: sonarqube.ProjectInfo


async def create_project(
    context: automations.AutomationContext,
    automation: models.Automation,
    project: models.Project,
) -> None:
    """Create a SonarQube project for `project`

    1. creates the SonarQube project with project key formed from
       project.namespace.slug and project.slug
    2. saves the project key as a SonarQube identifier
    3. creates a SonarQube dashboard link if the `project_link_type_id`
       is configured in self.application.settings
    4. configure the SonarQube PR decoration if the project has a
       gitlab external ID
    """
    client = await sonarqube.create_client(context.application,
                                           automation.integration_name)
    sonar_project = await client.create_project(project)
    context[create_project] = SonarQubeContext(
        integration_name=automation.integration_name,
        project_info=sonar_project)
    context.add_callback(_delete_project)
    context.note_progress('created SonarQube project %s for Imbi project %s',
                          sonar_project.key, project.id)

    # NB -- project is deleted upon failure and the delete cascades to
    # other tables so there is no need to clean up here

    await context.run_query(
        'INSERT INTO v1.project_identifiers (external_id, integration_name,'
        '                                    project_id, created_by)'
        '     VALUES (%(project_key)s, %(integration_name)s, %(project_id)s,'
        '             %(user)s)', {
            'project_key': sonar_project.key,
            'integration_name': automation.integration_name,
            'project_id': project.id,
            'user': context.user.username,
        }, 'insert-project-identifiers')
    context.note_progress(
        'registered SonarQube identifier %s for Imbi project %s',
        sonar_project.key, project.id)

    settings = context.application.settings['automations']['sonarqube']
    if (link_type_id := settings.get('project_link_type_id')) is not None:
        await context.run_query(
            'INSERT INTO v1.project_links (project_id, link_type_id,'
            '                              created_by, url)'
            '     VALUES (%(project_id)s, %(link_type_id)s, %(user)s,'
            '             %(dashboard_url)s)', {
                'project_id': project.id,
                'link_type_id': link_type_id,
                'user': context.user.username,
                'dashboard_url': str(sonar_project.dashboard_url)
            }, 'insert-project-links')
        context.note_progress('created SonarQube link %s for Imbi project %s',
                              sonar_project.dashboard_url, project.id)

    identifiers = await models.project_identifiers(project.id,
                                                   context.application)
    for identifier in identifiers:
        if identifier.integration_name == 'gitlab':  # TODO ... sigh
            context.note_progress('identifier: %s -> %s',
                                  identifier.integration_name,
                                  identifier.external_id)
            await client.enable_pr_decoration(sonar_project,
                                              int(identifier.external_id))
            break


async def _delete_project(context: automations.AutomationContext,
                          _error: BaseException) -> None:
    try:
        sonar_info = typing.cast(SonarQubeContext, context[create_project])
    except KeyError:
        return

    try:
        client = await sonarqube.create_client(context.application,
                                               sonar_info.integration_name)
    except errors.ClientUnavailableError:
        pass
    else:
        context.note_progress('removing sonarqube project s due to error',
                              sonar_info.project_info.key)
        await client.remove_project(sonar_info.project_info)
