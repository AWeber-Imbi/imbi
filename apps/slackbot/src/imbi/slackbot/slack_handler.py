"""Slack Socket Mode integration for the Imbi bot.

Builds a slack-bolt app that responds to @-mentions and direct messages
by resolving the Slack user to an Imbi user, minting a per-user token,
reconstructing the thread's context, and running the Claude tool loop.

"""

from __future__ import annotations

import logging
import re
import typing

from slack_bolt.adapter.socket_mode.async_handler import (
    AsyncSocketModeHandler,
)
from slack_bolt.async_app import AsyncApp

from imbi_slackbot import agent, identity, mcp, settings, system_prompt

# slack_sdk's AsyncWebClient is only loosely typed; treat it as Any
# rather than thread Unknown generics through every call site.
SlackClient = typing.Any

LOGGER = logging.getLogger(__name__)

_MENTION_RE = re.compile(r'<@[A-Z0-9]+>')

_NO_USER_MESSAGE = (
    "I couldn't match your Slack account to an Imbi user. Imbi matches "
    'you by your email address — ask an Imbi administrator to make sure '
    'your account exists and is active.'
)
_EMPTY_MESSAGE = (
    'Hi! Ask me anything about your Imbi projects, teams, or data.'
)

_app: AsyncApp | None = None
_handler: AsyncSocketModeHandler | None = None
_bot_user_id: str | None = None


def _strip_mentions(text: str) -> str:
    """Remove Slack ``<@USER>`` mention tokens from text."""
    return _MENTION_RE.sub('', text).strip()


def _reconstruct_messages(
    replies: list[dict[str, typing.Any]],
    bot_user_id: str,
    max_messages: int,
) -> list[dict[str, typing.Any]]:
    """Turn Slack thread messages into Anthropic message history.

    Bot messages become ``assistant`` turns, everything else ``user``.
    Consecutive same-role turns are coalesced and any leading assistant
    turns are dropped so the history alternates and starts with a user
    message, as the Anthropic API requires.

    """
    turns: list[dict[str, typing.Any]] = []
    for msg in replies[-max_messages:]:
        if msg.get('subtype'):
            continue
        author = msg.get('user')
        if not author:
            continue
        role = 'assistant' if author == bot_user_id else 'user'
        text = _strip_mentions(msg.get('text') or '')
        if not text:
            continue
        if turns and turns[-1]['role'] == role:
            turns[-1]['content'] = f'{turns[-1]["content"]}\n\n{text}'
        else:
            turns.append({'role': role, 'content': text})

    while turns and turns[0]['role'] == 'assistant':
        turns.pop(0)
    return turns


async def _load_thread(
    slack_client: SlackClient,
    channel: str,
    thread_ts: str,
    fallback: dict[str, typing.Any],
) -> list[dict[str, typing.Any]]:
    """Fetch a thread's messages, falling back to the triggering event."""
    try:
        response = await slack_client.conversations_replies(
            channel=channel,
            ts=thread_ts,
            limit=200,
        )
        messages: list[dict[str, typing.Any]] = response.get('messages') or []
    except Exception:
        LOGGER.exception('Failed to fetch thread %s/%s', channel, thread_ts)
        messages = []
    return messages or [fallback]


async def handle_event(
    event: dict[str, typing.Any],
    slack_client: SlackClient,
    *,
    bot_user_id: str,
) -> None:
    """Process a mention or DM and post the bot's reply in-thread."""
    channel = event.get('channel')
    ts = event.get('ts')
    slack_user_id = event.get('user')
    if not channel or not ts or not slack_user_id:
        return
    thread_ts = event.get('thread_ts') or ts

    user = await identity.resolve(slack_client, slack_user_id)
    if user is None:
        await slack_client.chat_postMessage(
            channel=channel, text=_NO_USER_MESSAGE, thread_ts=thread_ts
        )
        return

    slackbot_settings = settings.get_slackbot_settings()
    replies = await _load_thread(slack_client, channel, thread_ts, event)
    messages = _reconstruct_messages(
        replies, bot_user_id, slackbot_settings.max_thread_messages
    )
    if not messages:
        await slack_client.chat_postMessage(
            channel=channel, text=_EMPTY_MESSAGE, thread_ts=thread_ts
        )
        return

    token = identity.mint_token(user)
    manager = mcp.get_manager()
    tools = manager.get_tools() or None
    system = system_prompt.build_system_prompt(user, manager.get_tool_names())

    answer = await agent.run_turn(
        messages=messages,
        system=system,
        tools=tools,
        auth_token=token,
        model=slackbot_settings.model,
        max_tokens=slackbot_settings.max_tokens,
        max_rounds=slackbot_settings.max_tool_rounds,
    )
    await slack_client.chat_postMessage(
        channel=channel,
        text=answer or _EMPTY_MESSAGE,
        thread_ts=thread_ts,
    )


def _build_app(bot_token: str) -> AsyncApp:
    """Create the slack-bolt app and register event handlers."""
    app = AsyncApp(token=bot_token)

    @app.event('app_mention')  # pyright: ignore[reportUnknownMemberType]
    async def _on_mention(  # pyright: ignore[reportUnusedFunction]
        event: dict[str, typing.Any],
        client: SlackClient,
    ) -> None:
        await handle_event(event, client, bot_user_id=_bot_user_id or '')

    @app.event('message')  # pyright: ignore[reportUnknownMemberType]
    async def _on_message(  # pyright: ignore[reportUnusedFunction]
        event: dict[str, typing.Any],
        client: SlackClient,
    ) -> None:
        # Only handle direct messages here; channel mentions arrive as
        # app_mention. Ignore bot messages and edits/joins (subtypes).
        if event.get('channel_type') != 'im':
            return
        if event.get('bot_id') or event.get('subtype'):
            return
        await handle_event(event, client, bot_user_id=_bot_user_id or '')

    return app


async def initialize() -> None:
    """Build the Slack app and open the Socket Mode connection."""
    global _app, _handler, _bot_user_id

    slackbot_settings = settings.get_slackbot_settings()
    if not slackbot_settings.enabled:
        LOGGER.info('Slack bot disabled; not connecting to Slack')
        return
    if not (
        slackbot_settings.slack_bot_token and slackbot_settings.slack_app_token
    ):
        LOGGER.warning(
            'Slack bot enabled but SLACK_BOT_TOKEN / SLACK_APP_TOKEN '
            'are not both set; not connecting'
        )
        return

    _app = _build_app(slackbot_settings.slack_bot_token)
    auth = await _app.client.auth_test()  # pyright: ignore[reportUnknownMemberType]
    _bot_user_id = str(auth['user_id'])  # pyright: ignore[reportUnknownArgumentType]
    LOGGER.info('Connected to Slack as bot user %s', _bot_user_id)

    _handler = AsyncSocketModeHandler(_app, slackbot_settings.slack_app_token)
    await _handler.connect_async()  # type: ignore[no-untyped-call]
    LOGGER.info('Slack Socket Mode connection established')


async def aclose() -> None:
    """Close the Socket Mode connection."""
    global _app, _handler, _bot_user_id
    if _handler is not None:
        await _handler.close_async()  # type: ignore[no-untyped-call]
        _handler = None
    _app = None
    _bot_user_id = None
    identity.clear_cache()
