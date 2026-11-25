"""Block Kit builders for the Home tab, with the Slack length limits.

Each builder returns a plain ``dict``. A text that is too long is cut
with an ellipsis, so a long title from Imbi cannot make Slack refuse
the view. See https://docs.slack.dev/reference/block-kit/blocks.

"""

from __future__ import annotations

import re
import typing

type Block = dict[str, typing.Any]

#: The most blocks that a Home tab view or a modal can have.
MAX_BLOCKS = 100
SECTION_TEXT = 3000
FIELD_TEXT = 2000
CONTEXT_TEXT = 3000
BUTTON_TEXT = 75
OPTION_TEXT = 75
ID_LENGTH = 255
VALUE_LENGTH = 2000
URL_LENGTH = 3000
MAX_FIELDS = 10
MAX_CONTEXT = 10
MAX_ELEMENTS = 25
MAX_OVERFLOW = 5


def cut(text: str, limit: int) -> str:
    """Return ``text`` cut to ``limit`` characters, with an ellipsis."""
    return text if len(text) <= limit else text[: limit - 1] + '…'


#: An ``&`` that does not start an escape that :func:`escape` makes.
_BARE_AMP = re.compile(r'&(?!(?:amp|lt|gt);)')
#: A link target: http(s) only, no characters that end a Slack link.
_SAFE_URL = re.compile(r'^https?://[^\s|<>]+$', re.IGNORECASE)


def escape(text: str) -> str:
    """Escape the characters that Slack ``mrkdwn`` uses for links and
    mentions, so text from Imbi shows as written.

    The function is idempotent: text that it escaped already does not
    change, so a value can go through it more than one time.

    """
    return (
        _BARE_AMP.sub('&amp;', text).replace('<', '&lt;').replace('>', '&gt;')
    )


def unescape(text: str) -> str:
    """Undo :func:`escape`."""
    return text.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')


def safe_url(url: str | None) -> str | None:
    """Return ``url`` (unescaped) when it is an http(s) URL that cannot
    break out of a link, else ``None``."""
    if not url:
        return None
    raw = unescape(url)
    return raw if _SAFE_URL.match(raw) else None


def link(url: str | None, text: str) -> str:
    """Return a ``mrkdwn`` link to ``url`` with the text ``text``.

    Both are escaped here. A URL that is not a safe http(s) URL gives
    only the escaped text, with no link.

    """
    label = escape(text)
    target = safe_url(url)
    if target is None:
        return label
    return f'<{escape(target)}|{label.replace("|", "¦")}>'


def mrkdwn(text: str, limit: int = SECTION_TEXT) -> Block:
    return {'type': 'mrkdwn', 'text': cut(text, limit)}


def plain(text: str, limit: int = BUTTON_TEXT) -> Block:
    return {'type': 'plain_text', 'text': cut(text, limit), 'emoji': True}


def section(
    text: str | None,
    *,
    block_id: str | None = None,
    accessory: Block | None = None,
    fields: list[str] | None = None,
) -> Block:
    block: Block = {'type': 'section'}
    if text is not None:
        block['text'] = mrkdwn(text)
    if block_id:
        block['block_id'] = block_id[:ID_LENGTH]
    if accessory:
        block['accessory'] = accessory
    if fields:
        block['fields'] = [mrkdwn(f, FIELD_TEXT) for f in fields[:MAX_FIELDS]]
    return block


def context(*texts: str) -> Block:
    return {
        'type': 'context',
        'elements': [mrkdwn(t, CONTEXT_TEXT) for t in texts[:MAX_CONTEXT]],
    }


def divider() -> Block:
    return {'type': 'divider'}


def actions(elements: list[Block], block_id: str | None = None) -> Block:
    block: Block = {'type': 'actions', 'elements': elements[:MAX_ELEMENTS]}
    if block_id:
        block['block_id'] = block_id[:ID_LENGTH]
    return block


def button(
    text: str,
    action_id: str,
    *,
    url: str | None = None,
    value: str | None = None,
    style: typing.Literal['primary', 'danger'] | None = None,
) -> Block:
    element: Block = {
        'type': 'button',
        'action_id': action_id[:ID_LENGTH],
        'text': plain(text),
    }
    if url:
        element['url'] = url[:URL_LENGTH]
    if value is not None:
        if len(value) > VALUE_LENGTH:
            raise ValueError(f'Button value is over {VALUE_LENGTH}')
        element['value'] = value
    if style:
        element['style'] = style
    return element


def option(text: str, value: str) -> Block:
    return {'text': plain(text, OPTION_TEXT), 'value': value[:150]}


def overflow(action_id: str, options: list[tuple[str, str]]) -> Block:
    """Return an overflow menu. Slack takes 2 to 5 options."""
    if not 2 <= len(options) <= MAX_OVERFLOW:
        raise ValueError(f'An overflow takes 2 to 5 options: {options}')
    return {
        'type': 'overflow',
        'action_id': action_id[:ID_LENGTH],
        'options': [option(t, v) for t, v in options],
    }


def static_select(
    action_id: str,
    options: list[tuple[str, str]],
    initial: str | None = None,
    placeholder: str = 'Choose',
) -> Block:
    built = [option(t, v) for t, v in options[:100]]
    element: Block = {
        'type': 'static_select',
        'action_id': action_id[:ID_LENGTH],
        'placeholder': plain(placeholder),
        'options': built,
    }
    chosen = next((o for o in built if o['value'] == initial), None)
    if chosen:
        element['initial_option'] = chosen
    return element


def view(kind: str, blocks: list[Block], **extra: typing.Any) -> Block:
    """Return a view. Raise :class:`ValueError` above 100 blocks."""
    if len(blocks) > MAX_BLOCKS:
        raise ValueError(f'A view takes {MAX_BLOCKS} blocks: {len(blocks)}')
    return {'type': kind, 'blocks': blocks, **extra}
