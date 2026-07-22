"""Reconstruct Slack threads into Anthropic message history.

Turns a thread's replies into alternating ``user``/``assistant`` turns,
tagging each message with its author and Slack timestamp, converting
``<@id>`` mentions to display names, and ingesting supported file
attachments (images, PDFs, and text) as Anthropic content blocks.

Bot messages become ``assistant`` turns and everything else ``user``.
Consecutive same-role turns are coalesced (preserving per-speaker
attribution in the merged text) and any leading assistant turns are
dropped, so the history alternates and starts with a user message, as the
Anthropic API requires.

"""

from __future__ import annotations

import base64
import logging
import re
import typing

import httpx

# slack_sdk's AsyncWebClient is only loosely typed; treat it as Any rather
# than thread Unknown generics through every call site.
SlackClient = typing.Any
ContentBlock = dict[str, typing.Any]
Message = dict[str, typing.Any]

LOGGER = logging.getLogger(__name__)

_MENTION_RE = re.compile(r'<@([A-Z0-9]+)(?:\|[^>]+)?>')

# Images Claude accepts as image blocks (media type -> itself).
_IMAGE_MEDIA_TYPES = frozenset(
    {'image/gif', 'image/jpeg', 'image/png', 'image/webp'}
)
# Non-``text/*`` mimetypes that are safe to treat as UTF-8 text.
_TEXT_LIKE_MIMETYPES = frozenset(
    {
        'application/javascript',
        'application/json',
        'application/x-yaml',
        'application/xml',
    }
)
# Ambiguous mimetypes that may still be decodable text.
_BINARY_AMBIGUOUS_MIMETYPES = frozenset(
    {'application/force-download', 'application/octet-stream'}
)
# Largest attachment to download and forward to the model.
MAX_FILE_BYTES = 10 * 1024 * 1024


class _Turn(typing.NamedTuple):
    """An in-progress conversation turn before content collapsing."""

    role: str
    parts: list[ContentBlock]


def _text_block(text: str) -> ContentBlock:
    return {'type': 'text', 'text': text}


async def _display_name(
    slack_client: SlackClient,
    user_id: str,
    cache: dict[str, str],
) -> str:
    """Resolve a Slack user id to a display name (cached per call)."""
    if user_id in cache:
        return cache[user_id]
    name = user_id
    try:
        response: typing.Any = await slack_client.users_info(user=user_id)
        user: typing.Any = response['user'] or {}
        profile: typing.Any = user.get('profile') or {}
        name = (
            profile.get('display_name')
            or user.get('real_name')
            or user.get('name')
            or user_id
        )
    except Exception:  # noqa: BLE001
        LOGGER.warning('Failed to resolve display name for %s', user_id)
    cache[user_id] = name
    return name


async def _convert_mentions(
    slack_client: SlackClient,
    text: str,
    cache: dict[str, str],
) -> str:
    """Replace ``<@id>`` mention tokens with ``@display name``."""
    seen = {m.group(1) for m in _MENTION_RE.finditer(text)}
    if not seen:
        return text
    for user_id in seen:
        name = await _display_name(slack_client, user_id, cache)
        replacement = f'@{name}'

        def _replace(_match: re.Match[str], value: str = replacement) -> str:
            return value

        text = re.sub(rf'<@{re.escape(user_id)}(?:\|[^>]+)?>', _replace, text)
    return text


def _file_to_block(mimetype: str, content: bytes) -> ContentBlock:
    """Convert downloaded file bytes to an Anthropic content block."""
    mimetype = mimetype.split(';', 1)[0].strip().lower()
    if mimetype == 'application/pdf':
        return {
            'type': 'document',
            'source': {
                'type': 'base64',
                'media_type': 'application/pdf',
                'data': base64.b64encode(content).decode(),
            },
        }
    if mimetype in _IMAGE_MEDIA_TYPES:
        return {
            'type': 'image',
            'source': {
                'type': 'base64',
                'media_type': mimetype,
                'data': base64.b64encode(content).decode(),
            },
        }
    if mimetype.startswith('text/') or mimetype in _TEXT_LIKE_MIMETYPES:
        return _text_block(content.decode('utf-8', errors='replace'))
    if mimetype in _BINARY_AMBIGUOUS_MIMETYPES:
        try:
            return _text_block(content.decode('utf-8'))
        except UnicodeDecodeError:
            return _text_block(
                'ERROR: a binary file could not be decoded as text. '
                'Supported types are PDF, images, and text files.'
            )
    return _text_block(
        f'ERROR: unsupported file type {mimetype}. Supported types are '
        'PDF, images, and text files.'
    )


async def _file_blocks(
    http_client: httpx.AsyncClient,
    files: list[dict[str, typing.Any]],
) -> list[ContentBlock]:
    """Download a message's files and convert them to content blocks."""
    blocks: list[ContentBlock] = []
    for item in files:
        url = item.get('url_private_download') or item.get('url_private')
        if not url:
            continue
        try:
            async with http_client.stream(
                'GET', url, follow_redirects=False
            ) as response:
                if response.status_code != 200:
                    LOGGER.warning(
                        'Unable to download Slack file %s: HTTP %s',
                        url,
                        response.status_code,
                    )
                    continue
                mimetype = response.headers.get(
                    'content-type', 'application/octet-stream'
                )
                data = bytearray()
                oversized = False
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_FILE_BYTES:
                        oversized = True
                        break
        except httpx.HTTPError:
            LOGGER.warning('Failed to download Slack file %s', url)
            continue
        if oversized:
            blocks.append(
                _text_block(
                    f'ERROR: file exceeds the maximum size of '
                    f'{MAX_FILE_BYTES // (1024 * 1024)}MB.'
                )
            )
            continue
        blocks.append(_file_to_block(mimetype, bytes(data)))
    return blocks


def _coalesce(
    turns: list[_Turn], role: str, parts: list[ContentBlock]
) -> None:
    """Append a turn, merging into the previous one if same-role."""
    if turns and turns[-1].role == role:
        turns[-1].parts.extend(parts)
    else:
        turns.append(_Turn(role=role, parts=list(parts)))


def _collapse(turn: _Turn) -> Message:
    """Collapse a turn to ``{role, content}``; text-only -> a string."""
    if all(part['type'] == 'text' for part in turn.parts):
        text = '\n\n'.join(part['text'] for part in turn.parts)
        return {'role': turn.role, 'content': text}
    return {'role': turn.role, 'content': turn.parts}


async def reconstruct(
    slack_client: SlackClient,
    bot_token: str,
    replies: list[dict[str, typing.Any]],
    bot_user_id: str,
    max_messages: int,
) -> list[Message]:
    """Build Anthropic message history from a thread's replies.

    Args:
        slack_client: The Slack web client (for display-name lookups).
        bot_token: Slack bot token, used to download file attachments.
        replies: Raw Slack thread messages, oldest first.
        bot_user_id: The bot's Slack user id (its turns become assistant).
        max_messages: Only the most recent ``max_messages`` are replayed.

    """
    name_cache: dict[str, str] = {}
    http_client = httpx.AsyncClient(
        headers={'Authorization': f'Bearer {bot_token}'}, timeout=30
    )
    turns: list[_Turn] = []
    try:
        for msg in replies[-max_messages:]:
            if msg.get('subtype'):
                continue
            author = msg.get('user')
            if not author:
                continue
            role = 'assistant' if author == bot_user_id else 'user'
            text = await _convert_mentions(
                slack_client, msg.get('text') or '', name_cache
            )
            files: list[dict[str, typing.Any]] = msg.get('files') or []

            if role == 'assistant':
                if text.strip():
                    _coalesce(turns, role, [_text_block(text.strip())])
                continue

            display = await _display_name(slack_client, author, name_cache)
            prefix = f'<@{display}> [ts={msg.get("ts", "")}]'
            file_blocks = (
                await _file_blocks(http_client, files) if files else []
            )
            if not text.strip() and not file_blocks:
                continue
            header = f'{prefix} {text.strip()}'.rstrip()
            _coalesce(turns, role, [_text_block(header), *file_blocks])
    finally:
        await http_client.aclose()

    while turns and turns[0].role == 'assistant':
        turns.pop(0)
    return [_collapse(turn) for turn in turns]
