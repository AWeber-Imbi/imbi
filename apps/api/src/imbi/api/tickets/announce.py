"""Send ticket requests that wait on a person to the slackbot.

Each entry of :data:`imbi.common.valkey.TICKET_REQUESTS_STREAM` is one
request. The slackbot sends it as a direct message to ``recipient``, the
person on the ticket. An entry with ``escalation`` set comes from the
sweeper after the agent's response SLA, and the slackbot posts it to
``slack_channel``. It also posts there when the direct message fails.
"""

import logging
import typing

import orjson
from valkey import asyncio as valkey_asyncio

from imbi.common import valkey

LOGGER = logging.getLogger(__name__)

type Row = dict[str, typing.Any]

#: The request fields that the slackbot shows in its form.
FIELDS = ('kind', 'title', 'why', 'options', 'artifacts', 'artifact_digests')


def recipient(ticket: Row) -> str:
    """The person on the ticket: the assignee of a person ticket, else
    the owner."""
    if ticket['assignee_kind'] == 'person' and ticket['assignee']:
        return str(ticket['assignee'])
    return str(ticket['owner'])


def entry(
    ticket: Row, request: Row, routing: Row, *, escalation: bool = False
) -> Row:
    """Return the stream entry of ``request``.

    ``ticket`` has ``short_id``, ``title``, ``owner``, ``assignee_kind``
    and ``assignee``. ``routing`` has ``org_slug``, ``agent_name`` and
    ``slack_channel``. ``escalation`` sends the entry to the channel.
    """
    return {
        **routing,
        **({'escalation': True} if escalation else {}),
        'short_id': ticket['short_id'],
        'ticket_title': ticket['title'],
        'recipient': recipient(ticket),
        'request_id': str(request['id']),
        **{k: request[k] for k in FIELDS},
    }


async def publish(client: valkey_asyncio.Valkey | None, value: Row) -> None:
    """Add ``value`` to the stream. Best effort: when it fails, the
    request is still in the UI."""
    if client is None:
        return
    try:
        await client.xadd(
            valkey.TICKET_REQUESTS_STREAM,
            {'request': orjson.dumps(value)},
            maxlen=valkey.TICKET_REQUESTS_MAXLEN,
            approximate=True,
        )
    except Exception:
        LOGGER.exception(
            'Could not announce request %s of %s',
            value['request_id'],
            value['short_id'],
        )
