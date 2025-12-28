import dataclasses
import typing

from imbi import automations, errors, models
from imbi.clients import github


async def _get_associated_namespaces(
    context: automations.AutomationContext,
    namespace_id: int,
) -> list[str]:
    """Get associated namespace slugs for a given namespace.

    Args:
        context: Automation context for database queries
        namespace_id: The namespace ID to look up associations for

    Returns:
        List of associated namespace slugs (may be empty if no associations
        exist)
    """
    result = await context.run_query(
        'SELECT DISTINCT n.slug '
        'FROM v1.namespaces n '
        'JOIN v1.namespace_associations na ON n.id = na.child_namespace_id '
        'WHERE na.parent_namespace_id = %(namespace_id)s', {
            'namespace_id': namespace_id,
        },
        metric_name='get-namespace-associations')

    return [row['slug'] for row in result.rows]


@dataclasses.dataclass
class GitHubContext:
    integration_name: str
    repository: github.Repository


async def create_repository(
    context: automations.AutomationContext,
    automation: models.Automation,
    project: models.Project,
) -> None:
    """Create a GitHub repository for an Imbi project

    This automation creates the GitHub repository, adds the ID of the
    new repository as a project identifier, and sets the GitHub link
    if we have one configured. The repository is created in the GitHub
    organization associated with the Project Type slug.

    The github repository information is saved in the context using the
    function object (eg, `create_repository`) as the key.

    @see https://docs.github.com/en/rest/repos/repos?apiVersion=2022-11-28
    #create-an-organization-repository
    """
    client = await github.create_client(context.application,
                                        automation.integration_name,
                                        context.user)

    org = project.project_type.github_org or project.project_type.slug

    settings = context.application.settings['automations']['github']
    default_attributes = settings.get('default_respository_attributes', {})

    repository = await client.create_repository(
        org=org,
        name=project.slug,
        project_id=project.id,
        namespace_slug=project.namespace.slug,
        description=project.description,
        **default_attributes)

    context[create_repository] = GitHubContext(
        integration_name=automation.integration_name, repository=repository)
    context.add_callback(delete_repository)
    context.note_progress(
        'created GitHub repository %s/%s (id=%s) for Imbi project %s', org,
        repository.name, repository.id, project.id)

    associated_namespaces = await _get_associated_namespaces(
        context, project.namespace.id)

    if associated_namespaces:
        teams_to_assign = [ns.lower() for ns in associated_namespaces]
    else:
        # No associations, use the namespace itself
        teams_to_assign = [project.namespace.slug.lower()]

    for team_slug in teams_to_assign:
        try:
            await client.add_team_to_repository(org, project.slug, team_slug)
            context.note_progress('added team %s to GitHub repository %s/%s',
                                  team_slug, org, project.slug)
        except Exception as e:
            context.note_progress(
                'warning: failed to add team %s to repository %s/%s: %s',
                team_slug, org, project.slug, str(e))

    await context.run_query(
        'INSERT INTO v1.project_identifiers'
        '            (external_id, integration_name, project_id,'
        '             created_at, created_by)'
        '     VALUES (%(github_id)s, %(integration_name)s, %(imbi_id)s,'
        '             CURRENT_TIMESTAMP, %(username)s)', {
            'github_id': repository.id,
            'imbi_id': project.id,
            'integration_name': automation.integration_name,
            'username': context.user.username,
        })
    context.note_progress(
        'registered GitHub identifier %s for Imbi project %s', repository.id,
        project.id)

    link_type_id = settings.get('project_link_type_id', None)
    if link_type_id is not None:
        await context.run_query(
            'INSERT INTO v1.project_links'
            '            (project_id, link_type_id, created_by, url)'
            '     VALUES (%(imbi_id)s, %(link_type_id)s, %(username)s,'
            '             %(repository_url)s)', {
                'imbi_id': project.id,
                'link_type_id': link_type_id,
                'repository_url': repository.html_url,
                'username': context.user.username,
            })
        context.note_progress('created GitHub link %r for Imbi project %s',
                              repository.html_url, project.id)


async def delete_repository(context: automations.AutomationContext,
                            _error: BaseException):
    """Compensating action that deletes a GitHub repository

    The repository information is expected to be in
    ``context[create_repository]``.
    """
    try:
        github_info = typing.cast(GitHubContext, context[create_repository])
    except KeyError:
        return

    try:
        client = await github.create_client(context.application,
                                            github_info.integration_name,
                                            context.user)
    except errors.ClientUnavailableError:
        pass
    else:
        org = github_info.repository.owner.login
        repo = github_info.repository.name
        await client.delete_repository(org, repo)
