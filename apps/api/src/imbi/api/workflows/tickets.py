"""The attributes of an agent task (a ticket, ADR 0028) in a workflow.

The output of an ``agent`` step, the payload of a
``ticket_state_changed`` trigger, and the ticket block of a ``slack``
step show them.
"""

import typing

from imbi.api import settings
from imbi.common import graph
from imbi.common.workflows.registry import slack

_SLUGS_QUERY: typing.LiteralString = """
MATCH (o:Organization {{id: {org}}})
OPTIONAL MATCH (a:Agent {{id: {agent}}})-[:BELONGS_TO]->(o)
RETURN o.slug AS org_slug, a.slug AS agent_slug
"""


def url(org_slug: str, short_id: str) -> str | None:
    """Return the UI link of a task. ``None`` when ``IMBI_UI_URL`` is
    not set."""
    base = settings.get_server_config().ui_url
    return f'{base}/tickets/{org_slug}/{short_id}' if base else None


def project(task: dict[str, typing.Any]) -> str | None:
    """Return the slug of the first project of a task, if any."""
    projects: list[dict[str, str]] = task.get('projects') or []
    return projects[0]['project_slug'] if projects else None


async def attributes(
    db: graph.Graph | None, task: dict[str, typing.Any]
) -> dict[str, typing.Any]:
    """Return ``title``, ``url``, ``project``, ``agent`` (the agent
    slug), ``cost_usd``, ``type``, ``priority``, ``due_date``,
    ``labels``, and ``roles`` of a task. Without ``db``, ``url`` and
    ``agent`` are ``None``."""
    found = (
        await db.execute(
            _SLUGS_QUERY,
            {'org': task['organization_id'], 'agent': task['agent_id']},
            ['org_slug', 'agent_slug'],
        )
        if db is not None
        else []
    )
    row = found[0] if found else {}
    org_slug = graph.parse_agtype(row.get('org_slug'))
    return {
        'title': task['title'],
        'url': url(org_slug, task['short_id']) if org_slug else None,
        'project': project(task),
        'agent': graph.parse_agtype(row.get('agent_slug')),
        'cost_usd': float(task['cost_total']),
        'type': task.get('type'),
        'priority': task.get('priority'),
        'due_date': due.isoformat() if (due := task.get('due_date')) else None,
        'labels': task.get('labels'),
        'roles': task.get('roles'),
    }


def with_ticket_block(
    text: str, task: dict[str, typing.Any], org_slug: str
) -> str:
    """Return ``text`` with a block that shows ``task``.

    Each value from the task goes through :func:`slack.escape`, so a
    title cannot add a mention. The text is cut to keep the message in
    :data:`slack.MAX_TEXT`.
    """
    label = slack.escape(f'{task["short_id"]}: {task["title"]}')
    link = url(org_slug, task['short_id'])
    details = [
        f'Status: {task["status"]}',
        f'Outcome: {task["outcome"] or "none"}',
        f'Project: {project(task) or "none"}',
    ]
    heading = f'<{link}|{label}>' if link else label
    block = f'\n\n*{heading}*\n' + slack.escape(' | '.join(details))
    return text[: slack.MAX_TEXT - len(block)] + block
