"""SDK messages to ADR 0020 task events (plan section 6.6).

| SDK output | Task event |
|---|---|
| Assistant text | ``turn``, ``kind: text`` |
| Thinking block | ``turn``, ``kind: thinking`` |
| Tool use and its result | ``tool.called`` with arguments and result |
| Subagent output | the same, with ``parent_call_id`` |
| ``TodoWrite`` | ``todos.updated`` |

Each payload is redacted before it is queued. A ``turn`` or
``tool.called`` payload over :data:`PAYLOAD_LIMIT` is split into
continuation events: the same ``call_id``, with ``part`` and ``parts``.
The first part has every field; each part has a piece of the large
field (``body`` or ``result``). A reader joins the pieces in ``part``
order.
"""

import datetime
import json
import logging
import time
import typing
import uuid

import claude_agent_sdk as sdk

if typing.TYPE_CHECKING:
    from imbi.harness import redact

type Event = dict[str, typing.Any]

LOGGER = logging.getLogger(__name__)

#: The largest ``turn`` or ``tool.called`` payload, in bytes of JSON
#: (imbi-api ``MAX_LARGE_PAYLOAD_BYTES``), less a margin.
PAYLOAD_LIMIT = 1024 * 1024 - 1024
#: The largest payload of every other type (imbi-api
#: ``MAX_PAYLOAD_BYTES``), less a margin.
SMALL_LIMIT = 64 * 1024 - 1024
#: The most event bytes that wait for the next flush while imbi-api is
#: not reachable. Past it, the oldest events are dropped.
PENDING_LIMIT = 64 * 1024 * 1024
#: The largest payload total of one batch, less a margin.
BATCH_LIMIT = 4 * 1024 * 1024 - 4096
BATCH_EVENTS = 100
MAX_PARTS = 1000
#: The tools that change something outside the model.
MUTATING = frozenset(
    {
        'Bash',
        'Edit',
        'MultiEdit',
        'NotebookEdit',
        'Write',
        'mcp__imbi__run_with_secret',
    }
)
_LARGE = {'turn': 'body', 'tool.called': 'result'}


def size(payload: typing.Any) -> int:
    """The size of ``payload`` as imbi-api measures it (compact JSON)."""
    return len(
        json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode()
    )


def _pieces(text: str, first: int, rest: int) -> list[str]:
    """Cut ``text`` so that each piece is at most ``first`` (the first)
    or ``rest`` bytes as a JSON string."""
    pieces: list[str] = []
    start = 0
    while start < len(text):
        budget = first if not pieces else rest
        end = min(len(text), start + budget)
        while (used := size(text[start:end])) > budget:
            # Escapes and UTF-8 make a character up to 6 bytes.
            end = start + max(1, (end - start) * budget // used - 1)
        pieces.append(text[start:end])
        start = end
    return pieces or ['']


def _preview(event: Event) -> Event:
    """An event over :data:`SMALL_LIMIT`, as a truncated preview."""
    payload = event['payload']
    LOGGER.warning(
        'Truncated a %s event of %d bytes', event['type'], size(payload)
    )
    text = json.dumps(payload, ensure_ascii=False)
    return {
        **event,
        'payload': {
            'truncated': True,
            'preview': _pieces(text, SMALL_LIMIT - 64, SMALL_LIMIT)[0],
        },
    }


def split(event: Event) -> list[Event]:
    """Return the event, or its continuation events when it is large.

    An event of another type over :data:`SMALL_LIMIT` becomes a
    truncated preview: imbi-api would refuse its whole batch.
    """
    payload: dict[str, typing.Any] = event['payload']
    field = _LARGE.get(event['type'])
    if field is None:
        return [event if size(payload) <= SMALL_LIMIT else _preview(event)]
    if size(payload) <= PAYLOAD_LIMIT:
        return [event]
    text = payload[field]
    if not isinstance(text, str):
        text = json.dumps(text)
    call_id = str(payload.get('call_id') or uuid.uuid4())
    # The largest part numbers, so the size of each part is an upper
    # bound.
    head = {**payload, 'call_id': call_id, 'part': MAX_PARTS}
    head['parts'] = MAX_PARTS
    head.pop(field)
    if size(head) > PAYLOAD_LIMIT // 4:
        # Large tool input (a Write of a large file): keep a preview.
        head['arguments'] = json.dumps(head.get('arguments'))[:65536]
        head['arguments_truncated'] = True
    tail = {'call_id': call_id, 'part': MAX_PARTS, 'parts': MAX_PARTS}
    # 4 bytes for the "":"" of the field name, and its name.
    overhead = len(field) + 4
    pieces = _pieces(
        text,
        PAYLOAD_LIMIT - size(head) - overhead,
        PAYLOAD_LIMIT - size(tail) - overhead,
    )[:MAX_PARTS]
    parts = len(pieces)
    return [
        {
            **event,
            'event_id': event['event_id'] if part == 1 else str(uuid.uuid4()),
            'payload': {
                **(head if part == 1 else tail),
                field: piece,
                'part': part,
                'parts': parts,
            },
        }
        for part, piece in enumerate(pieces, 1)
    ]


def batches(events: list[Event]) -> list[list[Event]]:
    """Group events into batches that imbi-api accepts."""
    out: list[list[Event]] = []
    total = 0
    for event in events:
        weight = size(event['payload'])
        if (
            not out
            or len(out[-1]) >= BATCH_EVENTS
            or total + weight > (BATCH_LIMIT)
        ):
            out.append([])
            total = 0
        out[-1].append(event)
        total += weight
    return out


def _text(content: str | list[dict[str, typing.Any]] | None) -> str:
    if content is None or isinstance(content, str):
        return content or ''
    return '\n'.join(
        str(block['text'])
        if block.get('type') == 'text'
        else json.dumps(block)
        for block in content
    )


class Recorder:
    """Collects the events of one task until :meth:`take`."""

    def __init__(self, redactor: redact.Redactor) -> None:
        self.redactor = redactor
        self.pending: list[Event] = []
        #: The relay's audit fields of a call (plan P7), by tool name
        #: and input.
        self.audit: (
            typing.Callable[[str, typing.Any], dict[str, typing.Any] | None]
            | None
        ) = None
        #: Tool use id to the tool policy decision (plan section 6.5).
        self.decisions: dict[str, dict[str, typing.Any]] = {}
        #: Tool use id to (name, input, start, parent call id).
        self.calls: dict[
            str, tuple[str, dict[str, typing.Any], float, str | None]
        ] = {}

    def _add(
        self, kind: str, payload: dict[str, typing.Any], parent: str | None
    ) -> None:
        if parent is not None:
            payload['parent_call_id'] = parent
        self.pending.extend(
            split(
                {
                    'event_id': str(uuid.uuid4()),
                    'type': kind,
                    'actor_kind': 'agent' if parent is None else 'subagent',
                    'at': datetime.datetime.now(datetime.UTC).isoformat(),
                    'payload': self.redactor.payload(payload),
                }
            )
        )

    def notice(self, text: str) -> None:
        """A warning for the people who read the task."""
        self._add('turn', {'kind': 'warning', 'body': text}, None)

    def message(self, message: typing.Any) -> None:
        if isinstance(message, sdk.AssistantMessage):
            self._assistant(message)
        elif isinstance(message, sdk.UserMessage) and isinstance(
            message.content, list
        ):
            for block in message.content:
                if isinstance(block, sdk.ToolResultBlock):
                    self._result(block)

    def _assistant(self, message: sdk.AssistantMessage) -> None:
        parent = message.parent_tool_use_id
        texts: list[str] = []
        for block in message.content:
            if isinstance(block, sdk.TextBlock):
                texts.append(block.text)
            elif isinstance(block, sdk.ThinkingBlock) and block.thinking:
                self._add(
                    'turn',
                    {'kind': 'thinking', 'body': block.thinking},
                    parent,
                )
            elif isinstance(block, sdk.ToolUseBlock):
                self.calls[block.id] = (
                    block.name,
                    block.input,
                    time.monotonic(),
                    parent,
                )
                if block.name == 'TodoWrite':
                    self._todos(block.input, parent)
        if texts:
            self._add(
                'turn',
                {
                    'kind': 'text',
                    'body': '\n'.join(texts),
                    'message_id': message.message_id,
                },
                parent,
            )

    def _todos(self, raw: dict[str, typing.Any], parent: str | None) -> None:
        items = typing.cast(
            'list[dict[str, typing.Any]]', raw.get('todos') or []
        )
        todos = [
            {
                'title': str(item.get('content', '')),
                'status': str(item.get('status', '')),
                'done': item.get('status') == 'completed',
            }
            for item in items
        ]
        self._add('todos.updated', {'todos': todos}, parent)

    def _result(self, block: sdk.ToolResultBlock) -> None:
        name, arguments, started, parent = self.calls.pop(
            block.tool_use_id, ('unknown', {}, time.monotonic(), None)
        )
        self._add(
            'tool.called',
            {
                'call_id': block.tool_use_id,
                'tool': name,
                'mutating': name in MUTATING,
                'arguments': arguments,
                'result': _text(block.content),
                'is_error': bool(block.is_error),
                'duration_ms': int((time.monotonic() - started) * 1000),
                **(
                    {'policy': self.decisions.pop(block.tool_use_id)}
                    if block.tool_use_id in self.decisions
                    else {}
                ),
                **(
                    {'relay': audit}
                    if self.audit and (audit := self.audit(name, arguments))
                    else {}
                ),
            },
            parent,
        )

    def take(self) -> list[Event]:
        taken, self.pending = self.pending, []
        return taken

    def requeue(self, unsent: list[Event]) -> None:
        """Put events that were not sent back before the new ones.

        imbi-api ignores an ``event_id`` that it has, so a retry writes
        nothing twice. Past :data:`PENDING_LIMIT` bytes, the oldest
        events are dropped, and a warning event says how many.
        """
        self.pending = unsent + self.pending
        sizes = [size(event['payload']) for event in self.pending]
        total, dropped = sum(sizes), 0
        while total > PENDING_LIMIT and dropped < len(sizes):
            total -= sizes[dropped]
            dropped += 1
        if dropped:
            LOGGER.warning(
                'Dropped %d task events: imbi-api is not reachable', dropped
            )
            self.pending = self.pending[dropped:]
            self._add(
                'turn',
                {
                    'kind': 'warning',
                    'body': f'{dropped} events of this task were lost while '
                    'Imbi was not reachable.',
                },
                None,
            )
