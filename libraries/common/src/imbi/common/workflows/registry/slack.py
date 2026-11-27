"""Slack: post a message to a Slack channel as the Imbi bot."""

import re
import typing

import pydantic

from imbi.common.workflows import graph, step_type

#: A Slack channel id: ``C`` for a channel, ``G`` for an older private
#: channel.
CHANNEL_ID = re.compile(r'^[CG][A-Z0-9]{8,}$')

#: A channel id, or one plain reference. A rendered reference that is
#: not a channel id fails the step with ``invalid_params``.
_CHANNEL = rf'^(?:[CG][A-Z0-9]{{8,}}|{graph.REFERENCE})$'

#: The short id of an agent task (a ticket, ADR 0028), or one plain
#: reference. A rendered reference that
#: is not a short id fails the step with ``invalid_params``.
TICKET = rf'^(?:T-[0-9]+|{graph.REFERENCE})$'

#: The timestamp of a Slack message, which is its id in the channel.
MESSAGE_TS = re.compile(r'^[0-9]{10}\.[0-9]{6}$')

#: A message timestamp, or one plain reference. A reference that has
#: no value, or whose value is not a message timestamp, fails the step
#: with ``invalid_params``.
_THREAD_TS = rf'^(?:[0-9]{{10}}\.[0-9]{{6}}|{graph.REFERENCE})$'


def escape(value: str) -> str:
    """Escape the control characters of Slack mrkdwn in ``value``.

    The engine applies it to each value that a template puts in a slack
    step, so a value from a webhook cannot add a mention such as
    ``<!channel>`` or a link with a false label. Text that the author
    writes is kept as written.
    """
    return (
        value.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    )


#: The longest ``text`` that Slack accepts.
MAX_TEXT = 40000


class Params(pydantic.BaseModel):
    channel: str = pydantic.Field(
        pattern=_CHANNEL,
        description='Channel ID, for example C0123456789. Invite the '
        'Imbi bot to the channel first.',
    )
    text: str = pydantic.Field(
        min_length=1,
        max_length=MAX_TEXT,
        description='The message, in Slack mrkdwn. Templates are allowed.',
    )
    ticket: str | None = pydantic.Field(
        default=None,
        pattern=TICKET,
        description='A ticket to show below the message: its title as a '
        'link, status, outcome, and project. A short id, for example '
        'T-12, or a reference such as {{ trigger.task_id }}.',
    )
    thread_ts: str | None = pydantic.Field(
        default=None,
        pattern=_THREAD_TS,
        description='A message of the channel to reply to in a thread. '
        'Its timestamp, for example 1700000000.000100, or a reference '
        'such as {{ tell.ts }}.',
    )


class Output(pydantic.BaseModel):
    channel: str
    #: The timestamp of the message. ``None`` when an operator marked an
    #: unknown send done.
    ts: str | None
    permalink: str | None


def required_permissions(params: dict[str, typing.Any]) -> set[str]:
    """A step with a ticket reads an agent task."""
    return {'ticket:read'} if params.get('ticket') else set()


STEP = step_type.StepType(
    type='slack',
    category='action',
    label='Slack message',
    description='Posts a message to a Slack channel.',
    params=Params,
    output=Output,
    sample_output={
        'channel': 'C0123456789',
        'ts': '1700000000.000100',
        'permalink': 'https://example.slack.com/archives/C0123456789'
        '/p1700000000000100',
    },
    side_effect=True,
    timeout_seconds=120,
    # Only ``slack_ratelimited`` is retried: nothing posted.
    retries=3,
    required_permissions=required_permissions,
)
