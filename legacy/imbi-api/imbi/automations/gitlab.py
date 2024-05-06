import dataclasses
import http
import typing

from imbi import automations, errors, models
from imbi.clients import gitlab


@dataclasses.dataclass
class GitLabContext:
    integration_name: str
    project_info: gitlab.ProjectInfo


async def create_project(
    context: automations.AutomationContext,
    automation: models.Automation,
    project: models.Project,
) -> None:
    """Create a GitLab repository for an Imbi project

    This automation creates the GitLab project, adds the ID of the
    new project as a project identifier, and sets the GitLab link
    of we have one configured. The project is created in the GitLab
    group associated with the Project namespace and the sub-path
    associated with the Project Type.

    The gitlab project information is saved in the context using the
    function object (eg, `create_project`) as the key.

    @see https://gitlab.aweber.io/help/api/projects.md#create-project
    """
    client = await gitlab.create_client(context.application,
                                        automation.integration_name,
                                        context.user)
    group_name = (
        (project.namespace.gitlab_group_name or project.namespace.slug),
        (project.project_type.gitlab_project_prefix
         or project.project_type.slug),
    )
    group_info = await client.fetch_group(*group_name)
    if not group_info:
        raise errors.ApplicationError(http.HTTPStatus.BAD_REQUEST,
                                      'misconfigured',
                                      'Group %r does not exist in GitLab',
                                      '/'.join(group_name),
                                      title='Imbi Misconfiguration')

    gitlab_info = await client.create_project(
        group_info,
        project.name,
        description=project.description,
        path=project.slug,
    )
    context[create_project] = GitLabContext(
        integration_name=automation.integration_name, project_info=gitlab_info)
    context.add_callback(delete_project)
    context.note_progress(
        'created GitLab project %s (id=%s) for Imbi project %s',
        gitlab_info.name_with_namespace, gitlab_info.id, project.id)

    await context.run_query(
        'INSERT INTO v1.project_identifiers'
        '            (external_id, integration_name, project_id,'
        '             created_at, created_by)'
        '     VALUES (%(gitlab_id)s, %(integration_name)s, %(imbi_id)s,'
        '             CURRENT_TIMESTAMP, %(username)s)', {
            'gitlab_id': gitlab_info.id,
            'imbi_id': project.id,
            'integration_name': automation.integration_name,
            'username': context.user.username,
        })
    context.note_progress(
        'registered GitLab identifier %s for Imbi project %s', gitlab_info.id,
        project.id)

    settings = context.application.settings['automations']['gitlab']
    link_type_id = settings.get('project_link_type_id', None)
    if link_type_id is not None:
        await context.run_query(
            'INSERT INTO v1.project_links'
            '            (project_id, link_type_id, created_by, url)'
            '     VALUES (%(imbi_id)s, %(link_type_id)s, %(username)s,'
            '             %(project_url)s)', {
                'imbi_id': project.id,
                'link_type_id': link_type_id,
                'project_url': gitlab_info.web_url,
                'username': context.user.username,
            })
        context.note_progress('created GitLab link %r for Imbi project %s',
                              gitlab_info.web_url, project.id)


async def delete_project(context: automations.AutomationContext,
                         _error: BaseException):
    """Compensating action that deletes a GitLab project

    The project information is expected to be in ``context[create_project]``.
    """
    try:
        gitlab_info = typing.cast(GitLabContext, context[create_project])
    except KeyError:
        return

    try:
        client = await gitlab.create_client(context.application,
                                            gitlab_info.integration_name,
                                            context.user)
    except errors.ClientUnavailableError:
        pass
    else:
        await client.delete_project(gitlab_info.project_info)
