"""The Home tab of the Imbi Slack app (Slack App Home PRD, phase 1).

The bot renders the tab when the user opens it and after each click.
Every API call runs as the user, with a token minted for them. The
layout (collapse, hide, order, options) is stored in imbi-api.

Action ids are ``home:<section>:<verb>``. Phase 1 handles the layout
verbs and New ticket, which opens the ``/create-ticket`` modal. Every
other button is a link to Imbi, and its handler only acks.

"""

from __future__ import annotations

import contextlib
import datetime
import logging
import re
import typing
import zoneinfo

import httpx
from slack_bolt.async_app import AsyncApp
from slack_sdk import errors

from imbi.common import valkey
from imbi.slackbot import create_ticket, identity, settings
from imbi.slackbot.home import prefs, render, sources

SlackClient = typing.Any
type Body = dict[str, typing.Any]

LOGGER = logging.getLogger(__name__)

ACTION = re.compile(r'^home:')
#: The layout verbs, with the words of their failure notice.
_VERBS = {
    'collapse': 'collapse',
    'hide': 'hide',
    'up': 'move up',
    'down': 'move down',
    'expand': 'expand',
    'org': 'change the organization of',
    'customize': 'save',
}


def register(app: AsyncApp) -> None:
    """Register the Home tab handlers on the slack-bolt app."""

    @app.event('app_home_opened')  # pyright: ignore[reportUnknownMemberType]
    async def _opened(  # pyright: ignore[reportUnusedFunction]
        event: Body, body: Body, client: SlackClient
    ) -> None:
        if event.get('tab') != 'home':
            return
        await refresh(
            client,
            event['user'],
            view_hash=sources.dig(event, 'view', 'hash'),
            ask_url=_ask_url(body.get('team_id'), body.get('api_app_id')),
        )

    @app.action(ACTION)  # pyright: ignore[reportUnknownMemberType]
    async def _action(  # pyright: ignore[reportUnusedFunction]
        ack: typing.Any, body: Body, client: SlackClient
    ) -> None:
        await ack()
        await handle_action(client, body)

    @app.view(render.CUSTOMIZE)  # pyright: ignore[reportUnknownMemberType]
    async def _submit(  # pyright: ignore[reportUnusedFunction]
        ack: typing.Any, body: Body, client: SlackClient
    ) -> None:
        await ack()
        await handle_submission(client, body)


def _ask_url(team_id: str | None, app_id: str | None) -> str:
    """Return the link to the Messages tab of the app."""
    if not team_id or not app_id:
        return ''
    return f'slack://app?team={team_id}&id={app_id}&tab=messages'


def _zone(name: str | None) -> zoneinfo.ZoneInfo:
    try:
        return zoneinfo.ZoneInfo(name or 'UTC')
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        return zoneinfo.ZoneInfo('UTC')


async def _resolve(slack: SlackClient, slack_user_id: str) -> typing.Any:
    """Return the Imbi user, ``None`` for no user, or ``False`` when
    Slack or the graph cannot answer (that is not "no user")."""
    try:
        return await identity.resolve(slack, slack_user_id)
    except Exception:
        LOGGER.exception('Could not resolve Slack user %s', slack_user_id)
        return False


async def _publish(
    slack: SlackClient, user_id: str, view: Body, view_hash: str | None
) -> None:
    kwargs: Body = {'user_id': user_id, 'view': view}
    if view_hash:
        kwargs['hash'] = view_hash
    await slack.views_publish(**kwargs)


async def refresh(
    slack: SlackClient,
    slack_user_id: str,
    *,
    view_hash: str | None = None,
    ask_url: str = '',
    preferences: prefs.Prefs | None = None,
) -> None:
    """Gather, render, and publish the Home tab of a Slack user.

    On a ``hash_conflict`` (a newer render was published), gather and
    render again one time, without the hash.

    """
    user = await _resolve(slack, slack_user_id)
    if user is False:
        return
    if user is None:
        await _publish(
            slack,
            slack_user_id,
            render.message_view(identity.NO_USER_MESSAGE),
            view_hash,
        )
        return
    for attempt in range(2):
        view = await _build(user, ask_url, preferences)
        try:
            await _publish(slack, slack_user_id, view, view_hash)
        except errors.SlackApiError as err:
            response: typing.Any = err.response
            if response.get('error') != 'hash_conflict' or attempt:
                raise
            view_hash = None
        else:
            return


async def _build(
    user: identity.ImbiUser, ask_url: str, preferences: prefs.Prefs | None
) -> Body:
    try:
        async with identity.api_client(user) as client:
            gathered, preferences = await sources.gather(
                client, user.email, preferences
            )
    except Exception:
        LOGGER.exception('Could not gather the Home tab of %s', user.email)
        return render.message_view(
            'Imbi is not available. Try again.', retry=True
        )
    gathered.ui_url = settings.get_slackbot_settings().ui_url
    gathered.ask_url = ask_url
    return render.render(
        user,
        preferences,
        gathered,
        datetime.datetime.now(datetime.UTC),
        _zone(user.tz),
    )


def _parse(action_id: str) -> tuple[str, str]:
    """Return the section and verb of ``home:<section>:<verb>``."""
    _, section, verb = [*action_id.split(':', 2), '', ''][:3]
    return section, verb


async def handle_action(slack: SlackClient, body: Body) -> None:
    """Run a layout action and render again. Link buttons only ack."""
    action: Body = body['actions'][0]
    section, verb = _parse(action['action_id'])
    if (section, verb) == ('header', 'new_ticket'):
        await _new_ticket(slack, body)
        return
    if verb == 'menu':
        verb = str(sources.dig(action, 'selected_option', 'value') or '')
    if verb != 'retry' and verb not in _VERBS:
        return
    slack_user_id: str = body['user']['id']
    user = await _resolve(slack, slack_user_id)
    if not user:
        return
    if verb == 'customize':
        await _open_customize(slack, user, body['trigger_id'])
        return
    store = valkey.get_client()
    await store.delete(sources.gathered_key(user.email))
    key = typing.cast('prefs.SectionKey', section)
    written: prefs.Prefs | None = None
    if verb == 'retry':
        await sources.drop(section)
    else:

        def apply(current: prefs.Prefs) -> None:
            if verb == 'org':
                current.org_slug = sources.dig(
                    action, 'selected_option', 'value'
                )
            elif verb in ('up', 'down'):
                prefs.move(current, key, -1 if verb == 'up' else 1)
            else:
                display: dict[str, prefs.Display] = {
                    'collapse': 'collapsed',
                    'hide': 'hidden',
                    'expand': 'expanded',
                }
                prefs.set_display(current, key, display[verb])

        written = await _change(store, user, apply, verb, section)
    await refresh(
        slack,
        slack_user_id,
        view_hash=sources.dig(body, 'view', 'hash'),
        ask_url=_ask_url(
            sources.dig(body, 'team', 'id'), body.get('api_app_id')
        ),
        preferences=written,
    )


async def _new_ticket(slack: SlackClient, body: Body) -> None:
    """Open the modal of the ``/create-ticket`` command."""

    async def acked() -> None:
        """The Home action is acked already."""

    await create_ticket.on_command(
        acked,
        {'trigger_id': body['trigger_id'], 'user_id': body['user']['id']},
        slack,
    )


async def _change(
    store: typing.Any,
    user: identity.ImbiUser,
    apply: typing.Callable[[prefs.Prefs], None],
    verb: str,
    section: str,
) -> prefs.Prefs | None:
    """Write a change of the preferences. On failure, store a notice
    for the next render (§5.8) and return ``None``."""
    try:
        async with identity.api_client(user) as client:
            return await prefs.change(client, apply)
    except httpx.HTTPError as err:
        LOGGER.warning('Could not %s %s: %s', verb, section, err)
        reason = 'Imbi is not available'
        if isinstance(err, httpx.HTTPStatusError):
            reason = f'Imbi answered {err.response.status_code}'
        title = prefs.TITLES.get(typing.cast('prefs.SectionKey', section))
        target = title or 'your Home settings'
        await store.set(
            sources.notice_key(user.email),
            f'Could not {_VERBS[verb]} {target}: {reason}.',
            ex=sources.NOTICE_TTL,
        )
        return None


async def _open_customize(
    slack: SlackClient, user: identity.ImbiUser, trigger_id: str
) -> None:
    current = prefs.Prefs()
    with contextlib.suppress(httpx.HTTPError):
        async with identity.api_client(user) as client:
            current = await prefs.read(client)
    await slack.views_open(
        trigger_id=trigger_id, view=render.customize_view(current)
    )


async def handle_submission(slack: SlackClient, body: Body) -> None:
    """Save the Customize Home modal and render the Home tab again."""
    slack_user_id: str = body['user']['id']
    user = await _resolve(slack, slack_user_id)
    if not user:
        return
    values: Body = body['view']['state']['values']
    store = valkey.get_client()
    await store.delete(sources.gathered_key(user.email))
    written = await _change(
        store,
        user,
        lambda current: render.apply_customize(current, values),
        'customize',
        'home',
    )
    await refresh(
        slack,
        slack_user_id,
        ask_url=_ask_url(
            sources.dig(body, 'team', 'id'), body.get('api_app_id')
        ),
        preferences=written,
    )
