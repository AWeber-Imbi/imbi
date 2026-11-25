"""Unfurl Imbi ticket and project links that people post in Slack.

Slack sends ``link_shared`` when a message holds a URL on a domain of
the app's ``unfurl_domains``. The bot reads each item from imbi-api as
the Slack user who posted the link, so the card shows only what that
person can read, and answers with ``chat.unfurl``: a Slack Work
Object (a task for a ticket, an item for a project). No card is made in
a Slack Connect channel or from the composer (docs/slackbot/index.md).

"""

from __future__ import annotations

import asyncio
import dataclasses
import datetime
import logging
import re
import typing
import urllib.parse

import httpx
from slack_sdk import errors

from imbi.common import api, environments
from imbi.slackbot import identity, settings
from imbi.slackbot.home import render

SlackClient = typing.Any
#: A JSON payload from Slack or imbi-api.
Json = typing.Any

LOGGER = logging.getLogger(__name__)

_TICKET = re.compile(r'^/tickets/(?P<org>[^/]+)/(?P<short_id>[A-Za-z]+-\d+)')
_PROJECT = re.compile(r'^/projects/(?P<project_id>[^/]+)')

#: Slack fetches the image itself, so it must be on a public host.
LOGO_URL = (
    'https://raw.githubusercontent.com/AWeber-Imbi/imbi/main/'
    'ui/public/icons/pwa-192x192.png'
)
#: The prefix of the card buttons' ``action_id``.  The buttons open a
#: URL; Slack still sends ``block_actions``, which the bot only acks.
ACTION_PREFIX = 'unfurl_'
#: ``tag_color`` of each ticket status (Slack allows red, yellow,
#: green, gray, blue).
STATUS_COLORS = {
    'open': 'blue',
    'in_progress': 'yellow',
    'blocked': 'red',
    'closed': 'green',
}


@dataclasses.dataclass(frozen=True)
class Ticket:
    org: str
    short_id: str


@dataclasses.dataclass(frozen=True)
class Project:
    project_id: str


def parse(url: str) -> Ticket | Project | None:
    """Return the Imbi item that ``url`` links to, or ``None``."""
    ui_url = settings.get_slackbot_settings().ui_url
    if not ui_url:
        return None
    parsed = urllib.parse.urlsplit(url)
    if parsed.netloc.lower() != urllib.parse.urlsplit(ui_url).netloc.lower():
        return None
    if match := _TICKET.match(parsed.path):
        return Ticket(match['org'], match['short_id'])
    if match := _PROJECT.match(parsed.path):
        return Project(match['project_id'])
    return None


def ticket_entity(ticket: Json, url: str) -> Json:
    """Build the Work Object (a Slack task) for a ticket."""
    status = ticket.get('status')
    fields: Json = {
        'status': {
            'value': _title_case(status),
            'tag_color': STATUS_COLORS.get(status or '', 'gray'),
        },
        'priority': {'value': _title_case(ticket.get('priority'))},
    }
    if assignee := ticket.get('assignee'):
        user: Json = {'text': assignee}
        if '@' in assignee:  # Slack shows the matching Slack user.
            user['email'] = assignee
        fields['assignee'] = {'type': 'slack#/types/user', 'user': user}
    short_id = ticket.get('short_id') or ''
    return _entity(
        url,
        'slack#/entities/task',
        {'fields': fields},
        title=ticket.get('title') or short_id,
        display_type=_title_case(ticket.get('type')) or 'Ticket',
        display_id=short_id,
        buttons=[_button('Open in Imbi', url, primary=True)],
    )


def _title_case(value: str | None) -> str:
    """``in_progress`` -> ``In Progress``; ``''`` when there is no value."""
    return value.replace('_', ' ').title() if value else ''


def project_entity(project: Json, url: str) -> Json:
    """Build the Work Object for a ``ProjectListItem`` (``slim=true``)."""
    team: Json = project.get('team') or {}
    types: list[Json] = project.get('project_types') or []
    fields = [
        _string(
            'description', 'Description', project.get('description'), long=True
        ),
        _string('team', 'Team', team.get('name')),
        _string('type', 'Type', ', '.join(t['name'] for t in types)),
        _health(project.get('score')),
    ]
    if chips := drift_chips(project):
        fields.append(
            {
                'key': 'drift',
                'label': 'Drift',
                'type': 'array',
                'item_type': 'string',
                'value': chips,
            }
        )
    fields.extend(_current_release(project))
    buttons = [_button('Open in Imbi', url, primary=True)]
    if project.get('has_deployment_plugin'):
        ui_url = settings.get_slackbot_settings().ui_url
        deployments = f'{ui_url}/projects/{project["id"]}/deployments'
        buttons.append(_button('Deployments', deployments))
    return _entity(
        url,
        'slack#/entities/item',
        {'custom_fields': [f for f in fields if f]},
        title=project.get('name') or '',
        display_type='Project',
        display_id=project.get('slug') or '',
        buttons=buttons,
    )


def _string(
    key: str,
    label: str,
    value: str | None,
    color: str | None = None,
    *,
    long: bool = False,
) -> Json | None:
    value = (value or '').strip()
    if not value:
        return None
    field: Json = {
        'key': key,
        'label': label,
        'type': 'string',
        'value': value,
    }
    if color:
        field['tag_color'] = color
    if long:
        field['long'] = True
    return field


def _health(score: float | None) -> Json | None:
    """The score, colored by ``scoreBucket`` of the projects list.

    healthy is green, fair and at-risk are yellow, unhealthy is red.

    """
    if score is None:
        return None
    color = 'green' if score >= 85 else 'yellow' if score >= 50 else 'red'
    return _string('health', 'Health', str(round(score)), color)


def drift_chips(project: Json) -> list[Json]:
    """One chip per environment, in pipeline order.

    imbi-api computes the verdict (``drift_pairs`` and
    ``release_drifted``); the card only draws it.  An environment that
    is behind the one before it is red, with the days since the oldest
    commit that waits; the others are green.

    """
    pairs: list[Json] = project.get('drift_pairs') or []
    behind: dict[str, Json] = {p['base']['slug']: p for p in pairs}
    chips: list[Json] = []
    if project.get('release_drifted'):
        chips.append(_chip('Release', 'red'))
    for env in _pipeline(project):
        initial = env['name'][:1].upper()
        pair = behind.get(env['slug'])
        days = pair and _days_since(pair.get('oldest'))
        chips.append(
            _chip(
                f'{initial} {days}' if days else initial,
                'red' if pair else 'green',
            )
        )
    return chips


def _pipeline(project: Json) -> list[Json]:
    """The environments in pipeline order, as the projects list sorts."""
    return sorted(project.get('environments') or [], key=environments.sort_key)


def _chip(value: str, color: str) -> Json:
    return {'type': 'string', 'value': value, 'tag_color': color}


def _days_since(value: str | None) -> int | None:
    then = render.parse_when(value)
    return (datetime.datetime.now(datetime.UTC) - then).days if then else None


def _current_release(project: Json) -> list[Json]:
    """The release of the last environment in the pipeline."""
    envs = _pipeline(project)
    if not envs:
        return []
    last = envs[-1]
    releases: dict[str, Json] = project.get('current_releases') or {}
    release: Json = releases.get(last['slug']) or {}
    version: str | None = release.get('tag') or release.get('committish')
    deployed = render.parse_when(release.get('deployed_at'))
    if not version or not deployed:
        return []
    return [
        _string('release', last['name'], version),
        {
            'key': 'deployed',
            'label': 'Deployed',
            'type': 'slack#/types/timestamp',
            'value': int(deployed.timestamp()),
        },
    ]


def _button(text: str, url: str, *, primary: bool = False) -> Json:
    button: Json = {
        'text': text,
        'action_id': f'{ACTION_PREFIX}{text.lower().replace(" ", "_")}',
        'url': url,
    }
    if primary:
        button['style'] = 'primary'
    return button


def _entity(
    url: str,
    entity_type: str,
    payload: Json,
    *,
    title: str,
    display_type: str,
    display_id: str,
    buttons: list[Json],
) -> Json:
    return {
        'app_unfurl_url': url,
        'url': url,
        'external_ref': {'id': url},
        'entity_type': entity_type,
        'entity_payload': {
            'attributes': {
                'title': {'text': title},
                'display_type': display_type,
                'display_id': display_id,
                'product_name': 'Imbi',
                'product_icon': {'url': LOGO_URL, 'alt_text': 'Imbi'},
            },
            **payload,
            'actions': {'primary_actions': buttons},
        },
    }


def register(app: typing.Any) -> None:
    """Add the unfurl listeners to a Bolt app."""
    app.event('link_shared')(handle)
    # The card buttons open a URL; Slack still sends their clicks.
    app.action(re.compile(f'^{ACTION_PREFIX}'))(_ack)


async def _ack(ack: typing.Any) -> None:
    await ack()


async def handle(event: Json, client: SlackClient) -> None:
    """Answer a ``link_shared`` event with cards for the Imbi links."""
    links: list[Json] = event.get('links') or []
    urls: list[tuple[str, Ticket | Project]] = [
        (link['url'], item)
        for link in links
        if (item := parse(link.get('url') or '')) is not None
    ]
    if not urls or event.get('source') == 'composer':
        return
    if await _external(client, event.get('channel') or ''):
        return
    user = await identity.resolve(client, event.get('user') or '')
    if user is None:
        return
    async with identity.api_client(user) as imbi:
        orgs: list[Json] = []
        if any(isinstance(item, Project) for _, item in urls):
            orgs = await _get(imbi, '/organizations/') or []
        cards = await asyncio.gather(
            *(
                _ticket_card(imbi, item, url)
                if isinstance(item, Ticket)
                else _project_card(imbi, item, url, orgs)
                for url, item in urls
            )
        )
    entities = [card for card in cards if card]
    if not entities:
        return
    # Enterprise Grid events have no unfurl_id/source; use channel + ts.
    target = (
        {'unfurl_id': event['unfurl_id'], 'source': event['source']}
        if event.get('unfurl_id') and event.get('source')
        else {'channel': event.get('channel'), 'ts': event.get('message_ts')}
    )
    try:
        await client.chat_unfurl(metadata={'entities': entities}, **target)
    except errors.SlackApiError:
        LOGGER.warning('chat.unfurl failed', exc_info=True)


async def _external(client: SlackClient, channel: str) -> bool:
    """Return ``True`` unless the channel is known not to be shared
    with another organization. Fail closed."""
    try:
        response = await client.conversations_info(channel=channel)
    except errors.SlackApiError:
        LOGGER.warning('conversations.info failed for %s', channel)
        return True
    info: Json = response.get('channel') or {}
    return bool(info.get('is_ext_shared') or info.get('is_pending_ext_shared'))


async def _ticket_card(imbi: api.Imbi, item: Ticket, url: str) -> Json | None:
    path = f'/organizations/{item.org}/tickets/{item.short_id}'
    ticket = await _get(imbi, path)
    return ticket_entity(ticket, url) if ticket else None


async def _project_card(
    imbi: api.Imbi, item: Project, url: str, orgs: list[Json]
) -> Json | None:
    # ponytail: the project URL carries no org, so ask every org. A miss
    # costs one graph query. Upstream fix: an org-free project lookup in
    # imbi-api, or the org slug in project URLs.
    # The list endpoint alone carries the PR counts and drift data.
    params = {
        'slim': 'true',
        'include_archived': 'true',
        'project_id': item.project_id,
    }
    results = await asyncio.gather(
        *(
            _get(imbi, f'/organizations/{org["slug"]}/projects/', params)
            for org in orgs
        )
    )
    found = next((r[0] for r in results if r), None)
    return project_entity(found, url) if found else None


async def _get(
    imbi: api.Imbi, path: str, params: dict[str, str] | None = None
) -> Json:
    """GET ``path``; ``None`` for any answer but 200, or no answer."""
    try:
        response = await imbi.get(path, params=params)
    except httpx.HTTPError:
        LOGGER.debug('GET %s failed', path, exc_info=True)
        return None
    return response.json() if response.status_code == 200 else None
