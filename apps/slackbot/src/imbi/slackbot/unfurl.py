"""Unfurl Imbi ticket and project links that people post in Slack.

Slack sends ``link_shared`` when a message holds a URL on a domain of
the app's ``unfurl_domains``. The bot reads each item from imbi-api as
the Slack user who posted the link, so the card shows only what that
person can read, and answers with ``chat.unfurl``. No card is made in
a Slack Connect channel or from the composer (docs/slackbot/index.md).

"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import re
import typing
import urllib.parse

import httpx
from slack_sdk import errors

from imbi.common import api
from imbi.slackbot import blocks, identity, settings

SlackClient = typing.Any
#: A JSON payload from Slack or imbi-api.
Json = typing.Any

LOGGER = logging.getLogger(__name__)

_TICKET = re.compile(r'^/tickets/(?P<org>[^/]+)/(?P<short_id>[A-Za-z]+-\d+)')
_PROJECT = re.compile(r'^/projects/(?P<project_id>[^/]+)')


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


def ticket_blocks(ticket: Json, url: str) -> list[blocks.Block]:
    title = f'{ticket.get("short_id", "")} · {ticket.get("title") or ""}'
    team: Json = ticket.get('team') or {}
    return [
        blocks.section(f'*{blocks.link(url, title)}*'),
        _context(
            ticket.get('status'),
            ticket.get('priority'),
            ticket.get('type'),
            ticket.get('assignee'),
            team.get('name'),
        ),
    ]


def project_blocks(project: Json, url: str) -> list[blocks.Block]:
    text = f'*{blocks.link(url, project.get("name") or "")}*'
    description = (project.get('description') or '').strip().splitlines()
    if description:
        text += f'\n{blocks.escape(description[0])}'
    team: Json = project.get('team') or {}
    types: list[Json] = project.get('project_types') or []
    environments: list[Json] = project.get('environments') or []
    return [
        blocks.section(text),
        _context(
            team.get('name'),
            *(t.get('name') for t in types),
            *(e.get('name') for e in environments),
            'archived' if project.get('archived') else None,
        ),
    ]


def _context(*facts: object) -> blocks.Block:
    return blocks.context(
        ' · '.join(blocks.escape(str(f)) for f in facts if f)
    )


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
    unfurls = {
        url: {'blocks': card}
        for (url, _), card in zip(urls, cards, strict=True)
        if card
    }
    if not unfurls:
        return
    # Enterprise Grid events have no unfurl_id/source; use channel + ts.
    target = (
        {'unfurl_id': event['unfurl_id'], 'source': event['source']}
        if event.get('unfurl_id') and event.get('source')
        else {'channel': event.get('channel'), 'ts': event.get('message_ts')}
    )
    try:
        await client.chat_unfurl(unfurls=unfurls, **target)
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


async def _ticket_card(
    imbi: api.Imbi, item: Ticket, url: str
) -> list[blocks.Block] | None:
    path = f'/organizations/{item.org}/tickets/{item.short_id}'
    ticket = await _get(imbi, path)
    return ticket_blocks(ticket, url) if ticket else None


async def _project_card(
    imbi: api.Imbi, item: Project, url: str, orgs: list[Json]
) -> list[blocks.Block] | None:
    # ponytail: the project URL carries no org, so try each org in turn.
    # Upstream fix: an org-free project lookup in imbi-api, or the org
    # slug in project URLs.
    for org in orgs:
        path = f'/organizations/{org["slug"]}/projects/{item.project_id}'
        if project := await _get(imbi, path):
            return project_blocks(project, url)
    return None


async def _get(imbi: api.Imbi, path: str) -> Json:
    """GET ``path``; ``None`` for any answer but 200, or no answer."""
    try:
        response = await imbi.get(path)
    except httpx.HTTPError:
        LOGGER.debug('GET %s failed', path, exc_info=True)
        return None
    return response.json() if response.status_code == 200 else None
