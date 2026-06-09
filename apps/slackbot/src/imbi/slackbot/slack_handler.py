"""Slack Socket Mode integration for the Imbi bot.

Builds a slack-bolt app that responds to @-mentions and direct messages
by resolving the Slack user to an Imbi user, minting a per-user token,
reconstructing the thread's context, running the Claude tool loop while
showing progress, and rendering the reply as Slack-native formatting.

"""

from __future__ import annotations

import logging
import typing

from slack_bolt.adapter.socket_mode.async_handler import (
    AsyncSocketModeHandler,
)
from slack_bolt.async_app import AsyncApp
from slack_sdk import errors

from imbi_slackbot import (
    agent,
    identity,
    inflight,
    mcp,
    messages,
    settings,
    slackdwn,
    system_prompt,
)

# slack_sdk's AsyncWebClient is only loosely typed; treat it as Any
# rather than thread Unknown generics through every call site.
SlackClient = typing.Any

LOGGER = logging.getLogger(__name__)

_NO_USER_MESSAGE = (
    "I couldn't match your Slack account to an Imbi user. Imbi matches "
    'you by your email address — ask an Imbi administrator to make sure '
    'your account exists and is active.'
)
_EMPTY_MESSAGE = (
    'Hi! Ask me anything about your Imbi projects, teams, or data.'
)
_ERROR_MESSAGE = 'Sorry — something went wrong handling your request.'

_app: AsyncApp | None = None
_handler: AsyncSocketModeHandler | None = None
_bot_user_id: str | None = None


class _StatusReporter:
    """Post and update an in-thread status message during processing.

    Adds a status-emoji reaction to the triggering message and posts a
    single status message that is edited as the tool loop progresses,
    then both are cleared once the real answer is ready. All Slack calls
    are best-effort: a failure to show progress never fails the request.

    """

    def __init__(
        self,
        client: SlackClient,
        channel: str,
        thread_ts: str,
        event_ts: str,
        slackbot_settings: settings.Slackbot,
    ) -> None:
        self._client = client
        self._channel = channel
        self._thread_ts = thread_ts
        self._event_ts = event_ts
        self._enabled = slackbot_settings.progress_updates
        self._emoji = slackbot_settings.status_emoji
        self._status_ts: str | None = None
        self._emoji_added = False

    async def start(self) -> None:
        """Add the status reaction and post the initial status message."""
        if not self._enabled:
            return
        try:
            await self._client.reactions_add(
                channel=self._channel,
                timestamp=self._event_ts,
                name=self._emoji,
            )
            self._emoji_added = True
        except errors.SlackApiError:
            LOGGER.debug('Could not add status reaction', exc_info=True)
        await self.update('Thinking…')

    async def update(self, text: str) -> None:
        """Post (or edit) the status message with ``text``."""
        if not self._enabled:
            return
        body = f'_{text}_'
        try:
            if self._status_ts is None:
                response = await self._client.chat_postMessage(
                    channel=self._channel,
                    text=body,
                    thread_ts=self._thread_ts,
                )
                self._status_ts = response['ts'] if response else None
            else:
                await self._client.chat_update(
                    channel=self._channel, ts=self._status_ts, text=body
                )
        except errors.SlackApiError:
            LOGGER.debug('Could not update status message', exc_info=True)

    async def finish(self) -> None:
        """Delete the status message and remove the status reaction."""
        if self._status_ts is not None:
            try:
                await self._client.chat_delete(
                    channel=self._channel, ts=self._status_ts
                )
            except errors.SlackApiError:
                LOGGER.debug('Could not delete status message', exc_info=True)
            self._status_ts = None
        if self._emoji_added:
            try:
                await self._client.reactions_remove(
                    channel=self._channel,
                    timestamp=self._event_ts,
                    name=self._emoji,
                )
            except errors.SlackApiError:
                LOGGER.debug('Could not remove status reaction', exc_info=True)
            self._emoji_added = False


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
        thread: list[dict[str, typing.Any]] = response.get('messages') or []
    except Exception:
        LOGGER.exception('Failed to fetch thread %s/%s', channel, thread_ts)
        thread = []
    return thread or [fallback]


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

    async with inflight.track():
        await _process(
            event,
            slack_client,
            bot_user_id=bot_user_id,
            channel=channel,
            ts=ts,
            thread_ts=thread_ts,
            slack_user_id=slack_user_id,
        )


async def _process(
    event: dict[str, typing.Any],
    slack_client: SlackClient,
    *,
    bot_user_id: str,
    channel: str,
    ts: str,
    thread_ts: str,
    slack_user_id: str,
) -> None:
    """Resolve the user, run the turn, and post the rendered reply."""
    user = await identity.resolve(slack_client, slack_user_id)
    if user is None:
        await slack_client.chat_postMessage(
            channel=channel, text=_NO_USER_MESSAGE, thread_ts=thread_ts
        )
        return

    slackbot_settings = settings.get_slackbot_settings()
    replies = await _load_thread(slack_client, channel, thread_ts, event)
    convo = await messages.reconstruct(
        slack_client,
        slackbot_settings.slack_bot_token,
        replies,
        bot_user_id,
        slackbot_settings.max_thread_messages,
    )
    if not convo:
        await slack_client.chat_postMessage(
            channel=channel, text=_EMPTY_MESSAGE, thread_ts=thread_ts
        )
        return

    reporter = _StatusReporter(
        slack_client, channel, thread_ts, ts, slackbot_settings
    )
    await reporter.start()
    try:
        token = identity.mint_token(user)
        manager = mcp.get_manager()
        tools = manager.get_tools() or None
        system = system_prompt.build_system_prompt(
            user, manager.get_tool_names()
        )
        answer = await agent.run_turn(
            messages=convo,
            system=system,
            tools=tools,
            auth_token=token,
            model=slackbot_settings.model,
            max_tokens=slackbot_settings.max_tokens,
            max_rounds=slackbot_settings.max_tool_rounds,
            max_tool_result_chars=slackbot_settings.max_tool_result_chars,
            on_status=reporter.update,
        )
    except Exception:
        LOGGER.exception('Failed to handle event in %s/%s', channel, ts)
        answer = _ERROR_MESSAGE
    finally:
        await reporter.finish()

    sender = slackdwn.MarkdownSender(slack_client)
    await sender.send(channel, answer or _EMPTY_MESSAGE, thread_ts)


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
    """Drain in-flight work and close the Socket Mode connection."""
    global _app, _handler, _bot_user_id
    await inflight.wait_for_drain()
    if _handler is not None:
        await _handler.close_async()  # type: ignore[no-untyped-call]
        _handler = None
    _app = None
    _bot_user_id = None
    identity.clear_cache()
