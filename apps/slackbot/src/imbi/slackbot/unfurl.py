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

from imbi.common import api, environments, models
from imbi.slackbot import blocks, identity, settings

SlackClient = typing.Any
#: A JSON payload from Slack or imbi-api.
Json = typing.Any

LOGGER = logging.getLogger(__name__)

_TICKET = re.compile(r'^/tickets/(?P<org>[^/]+)/(?P<short_id>[A-Za-z]+-\d+)')
_PROJECT = re.compile(r'^/projects/(?P<project_id>[^/]+)')

#: The amber brand color (docs/design.md) for the card's side bar.
COLOR = '#ef9f27'
#: Slack fetches the image itself, so it must be on a public host.
LOGO_URL = (
    'https://raw.githubusercontent.com/AWeber-Imbi/imbi/main/'
    'ui/public/icons/pwa-192x192.png'
)


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
    fields = [
        f'*{name}*\n{_title_case(ticket.get(key))}'
        for name, key in (
            ('Status', 'status'),
            ('Priority', 'priority'),
            ('Type', 'type'),
        )
    ]
    fields.append(
        f'*Assignee*\n{blocks.escape(ticket.get("assignee") or "Unassigned")}'
    )
    return [
        blocks.section(f'*{blocks.link(url, title)}*', fields=fields),
        _context(team.get('name')),
    ]


def _title_case(value: str | None) -> str:
    """``in_progress`` -> ``In Progress``; ``—`` when there is no value."""
    return blocks.escape(value.replace('_', ' ').title()) if value else '—'


def project_blocks(project: Json, url: str) -> list[blocks.Block]:
    """Build the card from a ``ProjectListItem`` (``slim=true``)."""
    text = f'*{blocks.link(url, project.get("name") or "")}*'
    description = (project.get('description') or '').strip().splitlines()
    if description:
        text += f'\n{blocks.escape(description[0])}'
    score = project.get('score')
    drift = drift_labels(project)
    fields = [
        f'*Score*\n{"—" if score is None else round(score)}',
        f'*Open PRs*\n{project.get("open_pr_count") or 0}',
        f'*Drift*\n{blocks.escape(", ".join(drift)) if drift else "None"}',
    ]
    team: Json = project.get('team') or {}
    types: list[Json] = project.get('project_types') or []
    return [
        blocks.section(text, fields=fields),
        _context(
            team.get('name'),
            *(t.get('name') for t in types),
            'archived' if project.get('archived') else None,
        ),
    ]


def drift_labels(project: Json) -> list[str]:
    """The drift the projects list shows for ``project``.

    Mirrors ``driftSlugsFor`` in ``ui/src/components/ProjectsView.tsx``
    and the range key of ``_range_key`` in imbi-api's projects endpoint:
    a drifted environment pair counts unless the server proved its
    range clean, and a releasable project drifts with commits past its
    latest tag unless every one was answered ``false``.

    """
    types: list[Json] = project.get('project_types') or []
    delivery = models.resolve_delivery(
        project.get('delivery_mode'),
        deployable=any(t.get('deployable') for t in types),
        releasable=any(t.get('releasable') for t in types),
    )
    labels: list[str] = []
    if delivery.deployable:
        releases: Json = project.get('current_releases') or {}
        ranges: Json = project.get('drift_ranges') or {}
        envs: list[Json] = project.get('environments') or []
        for head_env, base_env in environments.promotion_pairs(envs):
            head: Json = releases.get(head_env['slug']) or {}
            base: Json = releases.get(base_env['slug']) or {}
            head_sha: str | None = head.get('committish')
            base_sha: str | None = base.get('committish')
            if head_sha and base_sha:
                # A range proven clean (every commit ``false``) is hidden.
                drifted = (
                    head_sha != base_sha
                    and ranges.get(f'{base_sha}..{head_sha}') is not False
                )
            else:
                drifted = (head.get('tag') or head_sha) != (
                    base.get('tag') or base_sha
                )
            if drifted:
                labels.append(f'{head_env["name"]} → {base_env["name"]}')
    summary: Json = project.get('release_summary') or {}
    if (
        delivery.releasable
        and summary.get('head_sha')
        and (summary.get('commits_since_tag') or 0) > 0
        and summary.get('drift_detected') is not False
    ):
        labels.append('Unreleased commits')
    return labels


def _context(*facts: object) -> blocks.Block:
    text = ' · '.join(blocks.escape(str(f)) for f in facts if f)
    elements: list[blocks.Block] = [
        {'type': 'image', 'image_url': LOGO_URL, 'alt_text': 'Imbi'}
    ]
    # Slack refuses an empty text element, and with it the whole unfurl.
    if text:
        elements.append(blocks.mrkdwn(text, blocks.CONTEXT_TEXT))
    return {'type': 'context', 'elements': elements}


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
        url: {'color': COLOR, 'blocks': card}
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
    return project_blocks(found, url) if found else None


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
