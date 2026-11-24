"""Post ticket requests that wait on a person to Slack, as forms.

imbi-api adds each new request of a ticket (ADR 0020) to
:data:`imbi.common.valkey.TICKET_REQUESTS_STREAM`. This module reads
the stream and posts a slackwright form with the same choices as the
"Waiting on you" box of the ticket in the UI. It posts to the Slack
channel of the agent. When the agent has no channel, or the bot cannot
find it, it sends a direct message to the owner of the ticket.

A submission resolves the request through imbi-api as the Slack user
who answered. The API checks ``ticket:resolve`` and records the
``slack`` channel, the same as for an answer in the UI.

"""

from __future__ import annotations

import asyncio
import logging
import re
import socket
import time
import typing

import httpx
import orjson
import pydantic
from slack_sdk import errors
from slackwright import forms, render

from imbi.common import api, valkey
from imbi.slackbot import identity, settings

SlackClient = typing.Any
type Entry = dict[str, typing.Any]

LOGGER = logging.getLogger(__name__)

GROUP = 'imbi-slackbot'
#: The key of the ticket request in the metadata of its form.
METADATA_KEY = 'ticket_request'
APPROVE = 'Approve'
REJECT = 'Reject'
#: The most options that a select and a radio take.
_MAX_OPTIONS = 100
_MAX_RADIO = 10
_MAX_OPTION_LENGTH = 75
_MAX_INTRO = 2000
_CHANNEL_ID = re.compile(r'^[CG][A-Z0-9]+$')
#: Slack errors that mean the bot cannot post to the channel.
_NO_CHANNEL = frozenset({'channel_not_found', 'is_archived', 'not_in_channel'})

#: Less than the socket timeout of the Valkey client (5 seconds), so an
#: empty poll returns before the socket times out.
_BLOCK_MS = 2000
#: An entry that a consumer read but did not ack for this long is posted
#: again, for example after the pod stopped during the post.
_CLAIM_IDLE_MS = 60_000
_PAGE_SIZE = 200
#: Seconds before a channel name that was not found is looked up again.
_MISS_TTL = 900

#: Channel ids by name. ponytail: a found channel never expires; a
#: renamed channel needs a restart.
_channels: dict[str, str] = {}
#: Names that were not found, with the time to look them up again.
_misses: dict[str, float] = {}


async def consume(slack: SlackClient, runtime: forms.Runtime) -> None:
    """Post the requests of the stream until the task is cancelled."""
    client = valkey.get_client()
    stream = valkey.TICKET_REQUESTS_STREAM
    consumer = socket.gethostname()
    ready = False
    while True:
        try:
            if not ready:
                await _create_group(client)
                ready = True
            # Entries that another consumer read and never acked, for
            # example when its pod stopped during the post. A claimed
            # entry can post a second form for the request.
            _, claimed, *_ = await client.xautoclaim(
                stream, GROUP, consumer, _CLAIM_IDLE_MS, count=10
            )
            response: list[typing.Any] = (
                await client.xreadgroup(
                    GROUP, consumer, {stream: '>'}, count=10, block=_BLOCK_MS
                )
                or []
            )
            messages = [*claimed, *(m for _, ms in response for m in ms)]
            for message_id, fields in messages:
                try:
                    raw = fields.get(b'request') or fields.get('request')
                    await post(slack, runtime, orjson.loads(raw))
                except Exception:
                    LOGGER.exception('Could not post %s', message_id)
                # ponytail: a failed post is not tried again. The request
                # stays open in the UI.
                await client.xack(stream, GROUP, message_id)
        except Exception:
            LOGGER.exception('Could not read %s', stream)
            ready = False
            await asyncio.sleep(5)


async def _create_group(client: typing.Any) -> None:
    """Create the consumer group at the start of the stream, so that the
    requests that imbi-api added before the first slackbot start are
    posted too."""
    try:
        await client.xgroup_create(
            valkey.TICKET_REQUESTS_STREAM, GROUP, id='0', mkstream=True
        )
    except Exception as err:
        if 'BUSYGROUP' not in str(err):
            raise


async def post(
    slack: SlackClient, runtime: forms.Runtime, entry: Entry
) -> None:
    """Post the form of ``entry`` to the agent channel or the owner."""
    name = entry.get('slack_channel')
    channel = name and await _channel_id(slack, name)
    if channel:
        try:
            await _post_form(slack, runtime, entry, channel)
        except errors.SlackApiError as err:
            # Only a definite "no such channel" goes to the owner. After
            # another error, Slack can have the post already.
            response: typing.Any = err.response
            if response.get('error') not in _NO_CHANNEL:
                raise
        else:
            return
    if name:
        LOGGER.warning(
            'No Slack channel %r for %s; sending to the owner',
            name,
            entry['short_id'],
        )
    channel = await _direct_channel(slack, entry['owner'])
    if not channel:
        LOGGER.info('No Slack user for %s', entry['owner'])
        return
    await _post_form(slack, runtime, entry, channel)


async def answer(slack: SlackClient, submission: forms.Submission) -> bool:
    """Resolve the request of a ticket request form.

    Return ``False`` when the form is not for a ticket request. Raise
    :class:`slackwright.forms.Rejected` when Imbi does not accept the
    answer.

    """
    entry: Entry | None = submission.metadata.get(METADATA_KEY)
    if entry is None:
        return False
    await _resolve(slack, entry, submission)
    return True


def form_spec(entry: Entry) -> forms.FormSpec:
    """Return the form of a request, with the choices of the UI box.

    Raises :class:`pydantic.ValidationError` when slackwright refuses
    the form, for example when the question names a secret.

    """
    raw: list[object] = entry.get('options') or []
    options = [_label(o) for o in raw]
    fields: list[dict[str, typing.Any]]
    if entry['kind'] == 'approval':
        fields = [
            {
                'type': 'radio',
                'id': 'decision',
                'label': 'Decision',
                'options': [APPROVE, REJECT],
            }
        ]
    elif options and _choosable(options):
        fields = [
            {
                'type': 'radio' if len(options) <= _MAX_RADIO else 'select',
                'id': 'choice',
                'label': 'Pick an answer',
                'options': options,
                'required': False,
            },
            {
                'type': 'text',
                'id': 'other',
                'label': 'Or write one',
                'multiline': True,
                'required': False,
            },
        ]
    else:
        fields = [
            {
                'type': 'text',
                'id': 'answer',
                'label': 'Your answer',
                'multiline': True,
            }
        ]
    return forms.FormSpec.model_validate(
        {
            'title': f'{entry["short_id"]} needs input'[:24],
            'intro': _intro(entry, options),
            'fields': fields,
            'submit_label': 'Send',
            'mode': 'inline',
            'respondents': 'anyone',
        }
    )


def resolution(entry: Entry, values: dict[str, typing.Any]) -> Entry | None:
    """Return the resolve body for the answers; ``None`` when empty."""
    if entry['kind'] == 'approval':
        if values.get('decision') == APPROVE:
            return {
                'status': 'approved',
                'artifact_digests': entry.get('artifact_digests') or [],
            }
        return {'status': 'rejected'}
    text = (values.get('other') or values.get('answer') or '').strip()
    text = text or values.get('choice') or ''
    return {'status': 'answered', 'answer': text} if text else None


async def _resolve(
    slack: SlackClient, entry: Entry, submission: forms.Submission
) -> None:
    """Resolve the request as the user who answered."""
    body = resolution(entry, submission.values)
    if body is None:
        raise forms.Rejected('Pick an answer or write one.')
    try:
        user = await identity.resolve(slack, submission.user_id)
    except Exception:
        LOGGER.exception('Could not resolve Slack user %s', submission.user_id)
        raise forms.Rejected('Imbi is not available. Try again.') from None
    if user is None:
        raise forms.Rejected('There is no Imbi user with your Slack email.')
    path = (
        f'/organizations/{entry["org_slug"]}/tickets/{entry["short_id"]}'
        f'/requests/{entry["request_id"]}/resolve'
    )
    try:
        async with api.Imbi(
            base_url=settings.get_slackbot_settings().api_base_url,
            token=identity.mint_token(user),
            timeout=10,
        ) as client:
            response = await client.post(path, json=body)
    except httpx.HTTPError:
        LOGGER.exception('Could not resolve %s', entry['request_id'])
        raise forms.Rejected('Imbi is not available. Try again.') from None
    _check(entry, response)


def _check(entry: Entry, response: httpx.Response) -> None:
    """Raise :class:`slackwright.forms.Rejected` for a refused answer.

    The form opens again when someone else can still answer it.

    """
    if response.is_success:
        return
    if response.status_code == 403:
        raise forms.Rejected('You do not have the ticket:resolve permission.')
    if response.status_code in (404, 409):
        detail = _detail(response)
        if detail.get('error') == 'request_resolved':
            message = f'{detail.get("resolved_by")} answered it first.'
        else:
            message = f'{detail.get("message") or "The request is gone"}.'
        raise forms.Rejected(message, retry=False)
    LOGGER.warning(
        'Resolve of %s failed: %s %s',
        entry['request_id'],
        response.status_code,
        response.text,
    )
    raise forms.Rejected('Imbi did not accept the answer.')


async def _post_form(
    slack: SlackClient, runtime: forms.Runtime, entry: Entry, channel: str
) -> None:
    try:
        spec = form_spec(entry)
    except pydantic.ValidationError as err:
        LOGGER.info('No form for %s: %s', entry['request_id'], err)
        # Do not repeat the question: slackwright refused it, for
        # example because it asks for a secret.
        text = (
            f'{_heading(entry)}\n\nThis ticket needs input. Answer it in Imbi.'
        )
        await render.post_markdown(slack, channel, None, text)
        return
    await runtime.post(
        slack,
        spec,
        channel_id=channel,
        thread_ts=None,
        requester='',
        metadata={METADATA_KEY: entry},
    )


async def _channel_id(slack: SlackClient, name: str) -> str | None:
    """Return the id of a channel by name (``#ops``, ``ops``) or id."""
    name = name.strip().lstrip('#')
    if _CHANNEL_ID.match(name):
        return name
    if name in _channels:
        return _channels[name]
    # Keep a miss for a time, so that an unknown name does not list all
    # channels again for each request.
    if _misses.get(name, 0.0) > time.monotonic():
        return None
    try:
        pages = await slack.conversations_list(
            types='public_channel,private_channel',
            exclude_archived=True,
            limit=_PAGE_SIZE,
        )
        async for page in pages:
            _channels.update({c['name']: c['id'] for c in page['channels']})
            if name in _channels:
                return _channels[name]
    except errors.SlackApiError as err:
        # For example missing_scope: the owner gets the request.
        response: typing.Any = err.response
        LOGGER.warning(
            'Could not list Slack channels: %s', response.get('error')
        )
        return None
    _misses[name] = time.monotonic() + _MISS_TTL
    return None


async def _direct_channel(slack: SlackClient, email: str) -> str | None:
    """Return the direct message channel with the Slack user of ``email``."""
    try:
        user = await slack.users_lookupByEmail(email=email)
    except errors.SlackApiError:
        return None
    opened = await slack.conversations_open(users=user['user']['id'])
    return str(opened['channel']['id'])


def _heading(entry: Entry) -> str:
    """Return a Markdown line that names and links the ticket."""
    ui_url = settings.get_slackbot_settings().ui_url
    ticket = entry['short_id']
    if ui_url:
        ticket = f'[{ticket}]({ui_url}/tickets/{entry["org_slug"]}/{ticket})'
    # The title is text of a person or an agent, so it must not notify
    # the channel.
    title = render.neutralize_broadcasts(entry['ticket_title'])
    return f'**{ticket}** · {title}'


def _intro(entry: Entry, options: list[str]) -> str:
    asker = entry.get('agent_name') or 'The agent'
    verb = 'asks for approval' if entry['kind'] == 'approval' else 'asks'
    parts = [_heading(entry), f'{asker} {verb}: **{entry["title"]}**']
    if entry.get('why'):
        parts.append(entry['why'])
    if entry.get('artifacts'):
        parts.append(
            'Artifacts:\n'
            + '\n'.join(f'- `{_label(a)}`' for a in entry['artifacts'])
        )
    if options and not _choosable(options):
        parts.append('Options:\n' + '\n'.join(f'- {o}' for o in options))
    intro = render.neutralize_broadcasts('\n\n'.join(parts))
    if len(intro) > _MAX_INTRO:
        intro = intro[: _MAX_INTRO - 1] + '…'
    return intro


def _choosable(options: list[str]) -> bool:
    """Return ``True`` when Slack can show ``options`` as choices."""
    return (
        len(options) <= _MAX_OPTIONS
        and len(set(options)) == len(options)
        and all(0 < len(o) <= _MAX_OPTION_LENGTH for o in options)
    )


def _label(value: object) -> str:
    """Return the text of an option or artifact, as the UI shows it."""
    return value if isinstance(value, str) else orjson.dumps(value).decode()


def _detail(response: httpx.Response) -> dict[str, typing.Any]:
    try:
        detail: object = response.json().get('detail')
    except ValueError:
        return {}
    if isinstance(detail, dict):
        return typing.cast('dict[str, typing.Any]', detail)
    return {}
