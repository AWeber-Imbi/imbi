"""Slack: post a message to a Slack channel as the Imbi bot."""

import re

import pydantic

from imbi.common.workflows import step_type

#: A Slack channel id: ``C`` for a channel, ``G`` for an older private
#: channel.
CHANNEL_ID = re.compile(r'^[CG][A-Z0-9]{8,}$')

#: A channel id, or one plain reference to a run-time value, as for the
#: ids of an email step. A rendered reference that is not a channel id
#: fails the step with ``invalid_params``.
_CHANNEL = (
    r'^(?:[CG][A-Z0-9]{8,}'
    r'|\{\{\s*[a-z][a-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\s*\}\})$'
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


class Output(pydantic.BaseModel):
    channel: str
    #: The timestamp of the message. ``None`` when an operator marked an
    #: unknown send done.
    ts: str | None
    permalink: str | None


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
)
