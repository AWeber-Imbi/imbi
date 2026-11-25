"""Send ticket requests that wait on a person to the slackbot.

Each entry of :data:`imbi.common.valkey.TICKET_REQUESTS_STREAM` is one
request. The slackbot sends it as a direct message to ``recipient``, the
person on the ticket. An entry with ``escalation`` set comes from the
sweeper after the agent's response SLA, and the slackbot posts it to
``slack_channel``. It also posts there when the direct message fails.
An entry with ``resolved`` set tells the slackbot that the request is
resolved (in the UI or in Slack) or withdrawn (by a hand-off).
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


#: The events that close a request, so that the slackbot closes its forms.
CLOSED_EVENTS = frozenset({'request.resolved', 'request.withdrawn'})


def closed(short_id: str, event: Row) -> Row:
    """Return the stream entry that tells the slackbot that a request is
    resolved or withdrawn, so that it replaces its forms with the
    decision. ``event`` is a :data:`CLOSED_EVENTS` event row."""
    payload: Row = event['payload']
    return {
        'resolved': True,
        'short_id': short_id,
        'request_id': payload['request_id'],
        'status': payload.get('status', 'withdrawn'),
        'answer': payload.get('answer'),
        'resolved_by': event['actor_id'],
    }


async def publish_closed(short_id: str, events: list[Row]) -> None:
    """Publish an entry for each event of ``events`` that closes a
    request. Nothing is published when Valkey is not set up."""
    entries = [
        closed(short_id, e) for e in events if e['type'] in CLOSED_EVENTS
    ]
    if not entries:
        return
    try:
        client = valkey.get_client()
    except RuntimeError:
        return
    for value in entries:
        await publish(client, value)


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
