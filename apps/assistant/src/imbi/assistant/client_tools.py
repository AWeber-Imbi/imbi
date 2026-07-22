"""Client-side tools that execute in the browser, not on the server.

These tools are included in Claude's tool definitions. When Claude
calls one, the backend streams a ``client_action`` SSE event to the
UI instead of executing it against the Imbi API. The UI then
performs the action (navigation, cache invalidation, etc.).

"""

import typing

CLIENT_TOOLS: list[dict[str, typing.Any]] = [
    {
        'name': 'navigate_to',
        'description': (
            "Navigate the user's browser to a path within the "
            'Imbi application. Use this after creating or looking '
            'up a resource to take the user directly to it. '
            'Examples: /projects, /admin/project-types, /dashboard'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'path': {
                    'type': 'string',
                    'description': (
                        'The application route path to navigate '
                        'to, e.g. "/projects" or '
                        '"/admin/environments"'
                    ),
                },
            },
            'required': ['path'],
        },
    },
    {
        'name': 'refresh_data',
        'description': (
            'Refresh data in the UI after creating, updating, or '
            'deleting a resource. This invalidates the browser '
            'cache so the user sees fresh data. Call this after '
            'any mutation tool (create, update, delete). The '
            'resource parameter must be one of: projects, '
            'project_types, environments, teams, organizations, '
            'blueprints, roles, users, service_accounts.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'resource': {
                    'type': 'string',
                    'description': 'The resource type to refresh.',
                    'enum': [
                        'projects',
                        'project_types',
                        'environments',
                        'teams',
                        'organizations',
                        'blueprints',
                        'roles',
                        'users',
                        'service_accounts',
                    ],
                },
                'org_slug': {
                    'type': 'string',
                    'description': (
                        'Organization slug, required for '
                        'org-scoped resources like '
                        'project_types, environments, and teams.'
                    ),
                },
            },
            'required': ['resource'],
        },
    },
]

_CLIENT_TOOL_NAMES = {t['name'] for t in CLIENT_TOOLS}


def is_client_tool(name: str) -> bool:
    """Check if a tool name is a client-side tool."""
    return name in _CLIENT_TOOL_NAMES


def get_tools() -> list[dict[str, typing.Any]]:
    """Return client tool definitions in Anthropic format."""
    return list(CLIENT_TOOLS)


def get_tool_names() -> list[str]:
    """Return the names of all client-side tools."""
    return list(_CLIENT_TOOL_NAMES)
