"""Permission-scoped Imbi tool definitions for Claude."""

import logging
import typing

from imbi_common import neo4j

from imbi_api.auth import permissions

LOGGER = logging.getLogger(__name__)

# Type for a tool handler function
ToolHandler = typing.Callable[
    [dict[str, typing.Any], permissions.AuthContext],
    typing.Awaitable[str],
]


class ToolDefinition(typing.NamedTuple):
    """A tool available to the assistant."""

    required_permission: str
    schema: dict[str, typing.Any]
    handler: ToolHandler


async def _handle_list_projects(
    params: dict[str, typing.Any],
    auth: permissions.AuthContext,
) -> str:
    """List projects the user can see."""
    limit = max(1, min(params.get('limit', 25), 100))
    name_filter = params.get('name_filter', '')

    query: typing.LiteralString = """
    MATCH (p:Project)-[:OWNED_BY]->(t:Team)
    OPTIONAL MATCH (p)-[:TYPE]->(pt:ProjectType)
    WHERE (
        $name_filter = '' OR
        toLower(p.name) CONTAINS toLower($name_filter)
    )
    RETURN p.name AS name, p.slug AS slug,
           p.description AS description,
           t.name AS team,
           pt.name AS project_type
    ORDER BY p.name
    LIMIT $limit
    """
    async with neo4j.run(
        query, limit=limit, name_filter=name_filter
    ) as result:
        records = await result.data()

    if not records:
        return 'No projects found.'

    lines = [f'Found {len(records)} project(s):\n']
    for r in records:
        desc = f' - {r["description"]}' if r.get('description') else ''
        team = f' (team: {r["team"]})' if r.get('team') else ''
        pt = f' [{r["project_type"]}]' if r.get('project_type') else ''
        lines.append(f'- **{r["name"]}**{pt}{team}{desc}')
    return '\n'.join(lines)


async def _handle_get_project(
    params: dict[str, typing.Any],
    auth: permissions.AuthContext,
) -> str:
    """Get details for a specific project."""
    slug = params.get('slug', '')
    if not slug:
        return 'Error: project slug is required.'

    query = """
    MATCH (p:Project {slug: $slug})-[:OWNED_BY]->(t:Team)
    OPTIONAL MATCH (p)-[:TYPE]->(pt:ProjectType)
    OPTIONAL MATCH (p)-[:DEPLOYED_IN]->(e:Environment)
    RETURN p, t.name AS team, pt.name AS project_type,
           collect(e.name) AS environments
    """
    async with neo4j.run(query, slug=slug) as result:
        records = await result.data()

    if not records:
        return f'Project with slug "{slug}" not found.'

    r = records[0]
    proj = neo4j.convert_neo4j_types(r['p'])

    lines = [
        f'# {proj.get("name", slug)}',
        '',
    ]
    if proj.get('description'):
        lines.append(proj['description'])
        lines.append('')
    lines.append(f'- **Slug**: {proj.get("slug", "N/A")}')
    lines.append(f'- **Team**: {r.get("team", "N/A")}')
    lines.append(f'- **Type**: {r.get("project_type", "N/A")}')
    envs = r.get('environments', [])
    if envs:
        lines.append(f'- **Environments**: {", ".join(envs)}')
    links = proj.get('links', {})
    if links:
        link_items = [f'[{k}]({v})' for k, v in links.items()]
        lines.append(f'- **Links**: {", ".join(link_items)}')
    return '\n'.join(lines)


async def _handle_list_blueprints(
    params: dict[str, typing.Any],
    auth: permissions.AuthContext,
) -> str:
    """List blueprints."""
    bp_type = params.get('type', '')

    query: typing.LiteralString = """
    MATCH (b:Blueprint)
    WHERE ($type = '' OR b.type = $type)
    RETURN b.name AS name, b.slug AS slug,
           b.type AS type, b.description AS description,
           b.enabled AS enabled
    ORDER BY b.type, b.name
    LIMIT 100
    """
    async with neo4j.run(query, type=bp_type) as result:
        records = await result.data()

    if not records:
        return 'No blueprints found.'

    lines = [f'Found {len(records)} blueprint(s):\n']
    for r in records:
        status = 'enabled' if r.get('enabled', True) else 'disabled'
        desc = f' - {r["description"]}' if r.get('description') else ''
        lines.append(f'- **{r["name"]}** ({r["type"]}, {status}){desc}')
    return '\n'.join(lines)


async def _handle_list_teams(
    params: dict[str, typing.Any],
    auth: permissions.AuthContext,
) -> str:
    """List teams."""
    query = """
    MATCH (t:Team)-[:BELONGS_TO]->(o:Organization)
    RETURN t.name AS name, t.slug AS slug,
           t.description AS description,
           o.name AS organization
    ORDER BY o.name, t.name
    LIMIT 100
    """
    async with neo4j.run(query) as result:
        records = await result.data()

    if not records:
        return 'No teams found.'

    lines = [f'Found {len(records)} team(s):\n']
    for r in records:
        desc = f' - {r["description"]}' if r.get('description') else ''
        lines.append(f'- **{r["name"]}** (org: {r["organization"]}){desc}')
    return '\n'.join(lines)


async def _handle_list_users(
    params: dict[str, typing.Any],
    auth: permissions.AuthContext,
) -> str:
    """List users."""
    limit = max(1, min(params.get('limit', 25), 100))
    active_only = params.get('active_only', True)

    query: typing.LiteralString = """
    MATCH (u:User)
    WHERE ($active_only = false OR u.is_active = true)
    RETURN u.email AS email, u.display_name AS display_name,
           u.is_admin AS is_admin, u.is_active AS is_active
    ORDER BY u.display_name
    LIMIT $limit
    """
    async with neo4j.run(
        query, limit=limit, active_only=active_only
    ) as result:
        records = await result.data()

    if not records:
        return 'No users found.'

    lines = [f'Found {len(records)} user(s):\n']
    for r in records:
        admin = ' [admin]' if r.get('is_admin') else ''
        active = '' if r.get('is_active', True) else ' (inactive)'
        lines.append(
            f'- **{r["display_name"]}** ({r["email"]}){admin}{active}'
        )
    return '\n'.join(lines)


# Tool registry
TOOLS: dict[str, ToolDefinition] = {
    'list_projects': ToolDefinition(
        required_permission='project:read',
        schema={
            'name': 'list_projects',
            'description': (
                'List projects in Imbi. Optionally filter by name.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'name_filter': {
                        'type': 'string',
                        'description': (
                            'Filter projects by name '
                            '(case-insensitive substring match)'
                        ),
                    },
                    'limit': {
                        'type': 'integer',
                        'description': 'Max results (default 25)',
                        'default': 25,
                    },
                },
            },
        },
        handler=_handle_list_projects,
    ),
    'get_project': ToolDefinition(
        required_permission='project:read',
        schema={
            'name': 'get_project',
            'description': (
                'Get detailed information about a specific project '
                'by its slug.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'slug': {
                        'type': 'string',
                        'description': 'The project slug',
                    },
                },
                'required': ['slug'],
            },
        },
        handler=_handle_get_project,
    ),
    'list_blueprints': ToolDefinition(
        required_permission='blueprint:read',
        schema={
            'name': 'list_blueprints',
            'description': 'List metadata blueprints in Imbi.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'type': {
                        'type': 'string',
                        'description': (
                            'Filter by type '
                            '(Team, Environment, ProjectType, Project)'
                        ),
                        'enum': [
                            'Team',
                            'Environment',
                            'ProjectType',
                            'Project',
                        ],
                    },
                },
            },
        },
        handler=_handle_list_blueprints,
    ),
    'list_teams': ToolDefinition(
        required_permission='team:read',
        schema={
            'name': 'list_teams',
            'description': ('List teams and their organizations in Imbi.'),
            'input_schema': {
                'type': 'object',
                'properties': {},
            },
        },
        handler=_handle_list_teams,
    ),
    'list_users': ToolDefinition(
        required_permission='user:read',
        schema={
            'name': 'list_users',
            'description': 'List users in Imbi.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'active_only': {
                        'type': 'boolean',
                        'description': (
                            'Only show active users (default true)'
                        ),
                        'default': True,
                    },
                    'limit': {
                        'type': 'integer',
                        'description': 'Max results (default 25)',
                        'default': 25,
                    },
                },
            },
        },
        handler=_handle_list_users,
    ),
}


def get_tools_for_user(
    user_permissions: set[str],
    is_admin: bool,
) -> tuple[list[dict[str, typing.Any]], list[str]]:
    """Get tool schemas and names available to a user.

    Args:
        user_permissions: Set of permission names the user has.
        is_admin: Whether the user is an admin.

    Returns:
        Tuple of (tool schemas, tool names).

    """
    schemas: list[dict[str, typing.Any]] = []
    names: list[str] = []
    for name, tool_def in TOOLS.items():
        if is_admin or tool_def.required_permission in user_permissions:
            schemas.append(tool_def.schema)
            names.append(name)
    return schemas, names


async def execute_tool(
    tool_name: str,
    tool_input: dict[str, typing.Any],
    auth: permissions.AuthContext,
) -> str:
    """Execute a tool by name.

    Args:
        tool_name: Name of the tool to execute.
        tool_input: Input parameters for the tool.
        auth: The user's auth context for permission checking.

    Returns:
        The tool's text result.

    """
    tool_def = TOOLS.get(tool_name)
    if not tool_def:
        return f'Unknown tool: {tool_name}'

    # Permission check
    if (
        not auth.user.is_admin
        and tool_def.required_permission not in auth.permissions
    ):
        return f'Permission denied for tool: {tool_name}'

    try:
        return await tool_def.handler(tool_input, auth)
    except Exception:
        LOGGER.exception('Tool execution failed: %s', tool_name)
        return f'Error executing tool {tool_name}.'
