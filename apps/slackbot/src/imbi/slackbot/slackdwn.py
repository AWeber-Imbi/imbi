"""Render Claude's Markdown answers as Slack messages.

Slack does not render standard Markdown (``**bold**``, ``## headings``,
``[label](url)`` links, tables, fenced code) in a plain ``text`` post.
:class:`MarkdownSender` parses the model output with ``markdown_it`` and:

- converts standard Markdown to Slack ``mrkdwn`` and posts short answers
  in a single message,
- falls back to Slack *blocks* for longer or table-bearing answers,
- uploads fenced code blocks as syntax-highlighted file snippets,
- renders Markdown tables as a channel canvas (with a text-snippet
  fallback when the canvas is too large or the API rejects it).

Adapted from the ``aj`` Slack bot. Decoupled from that project's
``slack_models.Channel``/``say`` plumbing: it takes a plain channel id and
posts through an injected Slack ``AsyncWebClient``.

"""

from __future__ import annotations

import asyncio
import collections.abc
import dataclasses
import logging
import re
import typing

import markdown_it
from markdown_it import token as markdown_token
from slack_sdk import errors

# slack_sdk's AsyncWebClient is only loosely typed (responses expose
# ``data`` as Any), so treat it as Any rather than thread Unknown generics
# through every call site — matching ``slack_handler``.
SlackClient = typing.Any

LOGGER = logging.getLogger(__name__)

_LANGUAGE_TO_SNIPPET_TYPE = {
    'bash': 'shell',
    'sh': 'shell',
    'shell': 'shell',
    'python': 'python',
    'py': 'python',
    'javascript': 'javascript',
    'js': 'javascript',
    'typescript': 'javascript',
    'ts': 'javascript',
    'java': 'java',
    'ruby': 'ruby',
    'rb': 'ruby',
    'cpp': 'c++',
    'c++': 'c++',
    'c': 'c',
    'csharp': 'csharp',
    'cs': 'csharp',
    'php': 'php',
    'go': 'go',
    'rust': 'rust',
    'rs': 'rust',
    'sql': 'sql',
    'xml': 'xml',
    'html': 'html',
    'css': 'css',
    'yaml': 'yaml',
    'yml': 'yaml',
    'json': 'json',
}

# Slack rejects a single message body above ~16k characters; longer
# answers are rendered as blocks instead.
_MARKDOWN_LIMIT = 16000

# A canvas has a practical cell ceiling; beyond it we fall back to a
# plain-text snippet.
_CANVAS_CELL_LIMIT = 300

_MRKDWN_LINK_RE = re.compile(r'<([^|>]+)\|([^>]+)>')
_MRKDWN_BOLD_RE = re.compile(r'(?<!\*)\*([^*]+)\*(?!\*)')


class _CanvasCreateError(Exception):
    """Raised when a canvas creation response is malformed."""


@dataclasses.dataclass
class _BlockState:
    """Mutable state for block-building during token parsing."""

    blocks: list[dict[str, typing.Any]] = dataclasses.field(
        default_factory=list
    )
    content: list[str] = dataclasses.field(default_factory=list)
    prefix: str | int | None = None
    responses: list[str] = dataclasses.field(default_factory=list)
    stack: collections.deque[str] = dataclasses.field(
        default_factory=collections.deque
    )
    plaintext: list[str] = dataclasses.field(default_factory=list)
    table_rows: list[list[str]] = dataclasses.field(default_factory=list)
    table_row: list[str] = dataclasses.field(default_factory=list)
    last_heading: str | None = None


def _mrkdwn_to_markdown(text: str) -> str:
    """Convert Slack mrkdwn to standard Markdown for canvas content.

    ``_process_inline`` emits ``<url|label>`` links and ``*bold*``
    emphasis; canvas ``document_content`` expects ``[label](url)`` and
    ``**bold**``.

    """
    text = _MRKDWN_LINK_RE.sub(r'[\2](\1)', text)
    return _MRKDWN_BOLD_RE.sub(r'**\1**', text)


class MarkdownSender:
    """Send Markdown text to Slack as mrkdwn/blocks with file uploads."""

    def __init__(self, client: SlackClient) -> None:
        """Initialize the sender with a Slack ``AsyncWebClient``."""
        self.client = client
        self.converter = markdown_it.MarkdownIt().enable('table')

    async def send(
        self,
        channel_id: str,
        text: str,
        thread_ts: str,
    ) -> list[str]:
        """Render ``text`` and post it to ``channel_id`` in-thread.

        Short, table-free answers are posted as a single mrkdwn message;
        longer or table-bearing answers are split into blocks, code
        snippets, and canvases. Returns the timestamps of the messages
        that were posted.

        """
        if not text.strip():
            return []
        LOGGER.debug('Sending to %s (%s): %s', channel_id, thread_ts, text)

        tokens = self.converter.parse(text)
        has_table = any(t.type == 'table_open' for t in tokens)
        if not has_table:
            formatted_text = self._convert_to_mrkdwn(text)
            if len(formatted_text) < _MARKDOWN_LIMIT:
                response_ts = await self._send_markdown(
                    channel_id, formatted_text, thread_ts
                )
                if response_ts is not None:
                    return [response_ts]
                LOGGER.warning('Markdown send failed, falling back to text')
                response_ts = await self._send_plaintext(
                    channel_id, text, thread_ts
                )
                return [response_ts] if response_ts else []

        return await self._send_as_blocks(channel_id, text, thread_ts, tokens)

    async def _send_as_blocks(
        self,
        channel_id: str,
        text: str,
        thread_ts: str,
        tokens: list[markdown_token.Token] | None = None,
    ) -> list[str]:
        """Parse markdown text into Slack blocks and send."""
        state = _BlockState()
        if tokens is None:
            tokens = self.converter.parse(text)
        for token in tokens:
            handler = self._token_handlers.get(token.type)
            if handler is not None:
                await handler(self, channel_id, thread_ts, state, token)
            else:  # pragma: nocover
                LOGGER.error('Unsupported token type %s', token.type)
                LOGGER.debug('%r', token)
        if state.blocks or state.plaintext:
            response_ts = await self._send_blocks(
                channel_id, state.blocks, state.plaintext, thread_ts
            )
            if response_ts is not None:
                state.responses.append(response_ts)
        return state.responses

    async def _handle_inline(
        self,
        _channel_id: str,
        _thread_ts: str,
        state: _BlockState,
        token: markdown_token.Token,
    ) -> None:
        inline_text = self._process_inline(token)
        if state.prefix and isinstance(state.prefix, int):
            state.content.append(f'{state.prefix}. {inline_text}')
            state.prefix += 1
        elif state.prefix:
            state.content.append(f'{state.prefix} {inline_text}')
        else:
            state.content.append(inline_text)

    async def _handle_open(
        self,
        _channel_id: str,
        _thread_ts: str,
        state: _BlockState,
        token: markdown_token.Token,
    ) -> None:
        state.stack.append(token.tag)

    async def _handle_bullet_list_open(
        self,
        _channel_id: str,
        _thread_ts: str,
        state: _BlockState,
        token: markdown_token.Token,
    ) -> None:
        state.prefix = '-'
        state.stack.append(token.tag)

    async def _handle_ordered_list_open(
        self,
        _channel_id: str,
        _thread_ts: str,
        state: _BlockState,
        token: markdown_token.Token,
    ) -> None:
        state.prefix = 1
        state.stack.append(token.tag)

    async def _handle_blockquote_close(
        self,
        _channel_id: str,
        _thread_ts: str,
        state: _BlockState,
        token: markdown_token.Token,
    ) -> None:
        state.stack = self._stack_remove(state.stack, token.tag)
        lines = '\n'.join(state.content).split('\n')
        quoted = '\n'.join([f'> {line}' for line in lines])
        self._append_section(state, quoted)
        state.content, state.prefix = [], None

    async def _handle_list_close(
        self,
        _channel_id: str,
        _thread_ts: str,
        state: _BlockState,
        token: markdown_token.Token,
    ) -> None:
        state.stack = self._stack_remove(state.stack, token.tag)
        if state.content:
            self._append_section(state, '\n'.join(state.content))
        state.content, state.prefix = [], None

    async def _handle_code(
        self,
        channel_id: str,
        thread_ts: str,
        state: _BlockState,
        token: markdown_token.Token,
    ) -> None:
        sent = await self._send_blocks(
            channel_id, state.blocks, state.plaintext, thread_ts
        )
        if sent is not None:
            state.responses.append(sent)
        state.responses.extend(
            await self._handle_code_block(channel_id, token, thread_ts)
        )
        state.blocks = []
        state.plaintext = []

    async def _handle_heading_close(
        self,
        _channel_id: str,
        _thread_ts: str,
        state: _BlockState,
        token: markdown_token.Token,
    ) -> None:
        state.stack = self._stack_remove(state.stack, token.tag)
        text = '\n'.join(state.content)
        state.blocks.append(
            {
                'type': 'header',
                'text': {'type': 'plain_text', 'text': text},
            }
        )
        state.plaintext.append(text)
        state.last_heading = text
        state.content = []

    async def _handle_hr(
        self,
        _channel_id: str,
        _thread_ts: str,
        state: _BlockState,
        _token: markdown_token.Token,
    ) -> None:
        state.blocks.append({'type': 'divider'})

    async def _handle_list_item_close(
        self,
        _channel_id: str,
        _thread_ts: str,
        state: _BlockState,
        token: markdown_token.Token,
    ) -> None:
        state.stack = self._stack_remove(state.stack, token.tag)

    async def _handle_paragraph_close(
        self,
        _channel_id: str,
        _thread_ts: str,
        state: _BlockState,
        token: markdown_token.Token,
    ) -> None:
        state.stack = self._stack_remove(state.stack, token.tag)
        if not state.stack and state.content:
            self._append_section(state, '\n'.join(state.content))
            state.content = []

    async def _handle_table_open(
        self,
        _channel_id: str,
        _thread_ts: str,
        state: _BlockState,
        token: markdown_token.Token,
    ) -> None:
        state.table_rows = []
        state.table_row = []
        state.stack.append(token.tag)

    async def _handle_tr_open(
        self,
        _channel_id: str,
        _thread_ts: str,
        state: _BlockState,
        token: markdown_token.Token,
    ) -> None:
        state.table_row = []
        state.stack.append(token.tag)

    async def _handle_cell_close(
        self,
        _channel_id: str,
        _thread_ts: str,
        state: _BlockState,
        token: markdown_token.Token,
    ) -> None:
        state.stack = self._stack_remove(state.stack, token.tag)
        state.table_row.append(' '.join(state.content))
        state.content = []

    async def _handle_tr_close(
        self,
        _channel_id: str,
        _thread_ts: str,
        state: _BlockState,
        token: markdown_token.Token,
    ) -> None:
        state.stack = self._stack_remove(state.stack, token.tag)
        state.table_rows.append(state.table_row)
        state.table_row = []

    async def _handle_section_close(
        self,
        _channel_id: str,
        _thread_ts: str,
        state: _BlockState,
        token: markdown_token.Token,
    ) -> None:
        state.stack = self._stack_remove(state.stack, token.tag)

    async def _handle_table_close(
        self,
        channel_id: str,
        thread_ts: str,
        state: _BlockState,
        token: markdown_token.Token,
    ) -> None:
        state.stack = self._stack_remove(state.stack, token.tag)
        if state.blocks or state.plaintext:
            response_ts = await self._send_blocks(
                channel_id, state.blocks, state.plaintext, thread_ts
            )
            if response_ts is not None:
                state.responses.append(response_ts)
        state.responses.extend(
            await self._render_table(
                channel_id, state.table_rows, thread_ts, state.last_heading
            )
        )
        state.blocks = []
        state.plaintext = []
        state.table_rows = []
        state.last_heading = None

    _token_handlers: typing.ClassVar[
        dict[str, typing.Callable[..., collections.abc.Awaitable[None]]]
    ] = {
        'inline': _handle_inline,
        'blockquote_open': _handle_open,
        'heading_open': _handle_open,
        'list_item_open': _handle_open,
        'paragraph_open': _handle_open,
        'bullet_list_open': _handle_bullet_list_open,
        'ordered_list_open': _handle_ordered_list_open,
        'blockquote_close': _handle_blockquote_close,
        'bullet_list_close': _handle_list_close,
        'ordered_list_close': _handle_list_close,
        'code_block': _handle_code,
        'fence': _handle_code,
        'heading_close': _handle_heading_close,
        'hr': _handle_hr,
        'list_item_close': _handle_list_item_close,
        'paragraph_close': _handle_paragraph_close,
        'table_open': _handle_table_open,
        'thead_open': _handle_open,
        'thead_close': _handle_section_close,
        'tbody_open': _handle_open,
        'tbody_close': _handle_section_close,
        'tr_open': _handle_tr_open,
        'tr_close': _handle_tr_close,
        'th_open': _handle_open,
        'th_close': _handle_cell_close,
        'td_open': _handle_open,
        'td_close': _handle_cell_close,
        'table_close': _handle_table_close,
    }

    @staticmethod
    def _append_section(state: _BlockState, text: str) -> None:
        """Append a mrkdwn section block and plaintext entry."""
        state.blocks.append(
            {
                'type': 'section',
                'text': {'type': 'mrkdwn', 'text': text},
            }
        )
        state.plaintext.append(text)

    async def _render_table(
        self,
        channel_id: str,
        rows: list[list[str]],
        thread_ts: str,
        title: str | None,
    ) -> list[str]:
        """Render a table as a Slack canvas with a snippet fallback."""
        if not rows:
            return []
        col_count = max(len(row) for row in rows)
        row_count = len(rows)
        fallback_reason: str | None = None
        if row_count * col_count > _CANVAS_CELL_LIMIT:
            fallback_reason = (
                f'{row_count * col_count} cells exceeds canvas limit '
                f'{_CANVAS_CELL_LIMIT}'
            )
        else:
            try:
                return await self._create_table_canvas(
                    channel_id, rows, thread_ts, title
                )
            except errors.SlackApiError as error:
                fallback_reason = str(error)
            except _CanvasCreateError as error:
                fallback_reason = str(error)
        LOGGER.warning(
            'Canvas render failed (%s); falling back to snippet',
            fallback_reason,
        )
        return await self._upload_table_snippet(
            channel_id, self._format_table_as_text(rows), thread_ts
        )

    async def _create_table_canvas(
        self,
        channel_id: str,
        rows: list[list[str]],
        thread_ts: str,
        title: str | None,
    ) -> list[str]:
        """Create a channel canvas containing the table and link it.

        Raises ``_CanvasCreateError`` when the response is missing the
        expected ``canvas_id``; callers handle the fallback.

        """
        canvas_title = title or 'Table'
        response = await self.client.conversations_canvases_create(
            channel_id=channel_id,
            document_content={
                'type': 'markdown',
                'markdown': self._format_table_as_markdown(rows),
            },
            title=canvas_title,
        )
        canvas_id = response.data.get('canvas_id')
        if not canvas_id:
            raise _CanvasCreateError(
                f'missing canvas_id in response: {response.data!r}'
            )
        permalink = await self._canvas_permalink(canvas_id)
        if permalink:
            link_text = f'📋 <{permalink}|{canvas_title}>'
        else:
            link_text = f'📋 {canvas_title} (canvas {canvas_id})'
        response_ts = await self._send_markdown(
            channel_id, link_text, thread_ts
        )
        if response_ts is None:
            raise _CanvasCreateError('failed to post canvas permalink')
        return [response_ts]

    async def _canvas_permalink(self, canvas_id: str) -> str | None:
        """Return a permalink URL for a canvas file, or ``None``."""
        try:
            info = await self.client.files_info(file=canvas_id)
        except errors.SlackApiError as error:
            LOGGER.warning(
                'files.info failed for canvas %s: %s', canvas_id, error
            )
            return None
        file_data = info.data.get('file')
        if not file_data:
            return None
        return typing.cast('str | None', file_data.get('permalink'))

    @staticmethod
    def _format_table_as_markdown(rows: list[list[str]]) -> str:
        """Format table rows as a standard Markdown table.

        Cells may contain Slack mrkdwn (``<url|label>``, ``*bold*``) from
        ``_process_inline``; canvas requires standard Markdown, so each
        cell is converted before formatting.

        """
        if not rows:
            return ''
        col_count = max(len(row) for row in rows)

        def _pad(row: list[str]) -> list[str]:
            padded = [
                _mrkdwn_to_markdown(cell).replace('|', r'\|') for cell in row
            ]
            while len(padded) < col_count:
                padded.append('')
            return padded

        lines = ['| ' + ' | '.join(_pad(rows[0])) + ' |']
        lines.append('| ' + ' | '.join(['---'] * col_count) + ' |')
        for row in rows[1:]:
            lines.append('| ' + ' | '.join(_pad(row)) + ' |')
        return '\n'.join(lines)

    @staticmethod
    def _format_table_as_text(rows: list[list[str]]) -> str:
        """Format table rows as column-aligned plain text."""
        if not rows:
            return ''
        col_count = max(len(row) for row in rows)
        widths = [0] * col_count
        for row in rows:
            for i, cell in enumerate(row):
                widths[i] = max(widths[i], len(cell))
        lines: list[str] = []
        for offset, row in enumerate(rows):
            cells = [cell.ljust(widths[i]) for i, cell in enumerate(row)]
            while len(cells) < col_count:
                cells.append(' ' * widths[len(cells)])
            lines.append('  '.join(cells).rstrip())
            if offset == 0:
                sep = ['─' * w for w in widths]
                lines.append('  '.join(sep))
        return '\n'.join(lines)

    @classmethod
    def _convert_to_mrkdwn(cls, text: str) -> str:
        """Convert standard Markdown to Slack mrkdwn format."""
        parts = re.split(r'(```[\s\S]*?```|`[^`\n]*`)', text)
        for i, part in enumerate(parts):
            if part.startswith('`'):
                continue
            # Headers: ## text -> *text* (strip optional closing hashes)
            converted = re.sub(
                r'^#{1,6}[ \t]+(.*?)(?:[ \t]+#+[ \t]*)?$',
                r'*\1*',
                part,
                flags=re.MULTILINE,
            )
            # Bold: **text** or __text__ -> *text*
            converted = re.sub(r'\*\*(.+?)\*\*', r'*\1*', converted)
            converted = re.sub(r'__(.+?)__', r'*\1*', converted)
            # Horizontal rules: ---, ***, ___, - - -, * * *, _ _ _
            converted = re.sub(
                r'^(?:(?:-[ \t]*){3,}|(?:\*[ \t]*){3,}|(?:_[ \t]*){3,})$',
                '─' * 40,
                converted,
                flags=re.MULTILINE,
            )
            # Links: [text](url) -> <url|text>
            # Supports one level of nested parens for URLs like
            # [f](https://en.wikipedia.org/wiki/Function_(mathematics))
            converted = re.sub(
                r'\[([^\]]+)\]\(((?:[^()\s]|\([^)]*\))+)\)',
                r'<\2|\1>',
                converted,
            )
            parts[i] = converted
        return ''.join(parts)

    @staticmethod
    def _get_snippet_type(language: str) -> str:
        """Convert a language identifier to a valid Slack snippet type."""
        return _LANGUAGE_TO_SNIPPET_TYPE.get(language.lower(), 'text')

    async def _handle_code_block(
        self,
        channel_id: str,
        token: markdown_token.Token,
        thread_ts: str,
    ) -> list[str]:
        """Upload a fenced code block as a file snippet."""
        title = f'Code: {token.info}' if token.info else 'Code Block'
        filetype = token.info.lower() if token.info else 'text'
        try:
            response = await self.client.files_upload_v2(
                channel=channel_id,
                content=token.content,
                filename=f'{title}.{filetype}',
                title=title,
                snippet_type=self._get_snippet_type(filetype),
                thread_ts=thread_ts,
            )
        except errors.SlackApiError:
            LOGGER.exception('Error uploading code snippet to Slack')
            return []
        # Give Slack time to process, otherwise ordering is wrong.
        await asyncio.sleep(1)
        response_ts: list[str] = []
        for file in response.data['files']:
            ts = await self._get_file_ts(channel_id, thread_ts, file['id'])
            if ts:
                response_ts.append(ts)
        return response_ts

    async def _upload_table_snippet(
        self,
        channel_id: str,
        content: str,
        thread_ts: str,
    ) -> list[str]:
        """Upload a formatted table as a text snippet."""
        try:
            response = await self.client.files_upload_v2(
                channel=channel_id,
                content=content,
                filename='Table.text',
                title='Table',
                snippet_type='text',
                thread_ts=thread_ts,
            )
        except errors.SlackApiError:
            LOGGER.exception('Error uploading table snippet to Slack')
            return []
        await asyncio.sleep(1)
        response_ts: list[str] = []
        for file in response.data['files']:
            ts = await self._get_file_ts(channel_id, thread_ts, file['id'])
            if ts:
                response_ts.append(ts)
        return response_ts

    async def _get_file_ts(
        self, channel_id: str, thread_ts: str, file_id: str
    ) -> str | None:
        """Resolve the message ts that carries an uploaded file."""
        try:
            result = await self.client.conversations_replies(
                channel=channel_id, ts=thread_ts
            )
        except errors.SlackApiError:
            LOGGER.warning(
                'conversations.replies failed while resolving file ts'
            )
            return None
        for message in result.data['messages']:
            for file in message.get('files', []):
                if file['id'] == file_id:
                    LOGGER.debug('Matched on %s', file['id'])
                    return typing.cast('str', message['ts'])
        return None

    def _process_inline(self, value: markdown_token.Token) -> str:
        """Handle text formatting of token child elements."""
        content: list[str] = []
        output: list[str] = []
        stack: collections.deque[str] = collections.deque()
        for child in value.children or []:
            accumulator = content if 'link_open' in stack else output
            if child.type == 'text':
                accumulator.append(child.content)
            elif child.type == 'code_inline':
                accumulator.append(f'`{child.content}`')
            elif child.type in ['em_open', 'em_close']:
                accumulator.append('_')
            elif child.type in ['strong_open', 'strong_close']:
                accumulator.append('*')
            elif child.type == 'link_open':
                accumulator.append(f'<{child.attrs["href"]}|')
                stack.append('link_open')
            elif child.type == 'link_close':
                accumulator.append('>')
                output.append(''.join(content))
                content = []
                if 'link_open' in stack:
                    stack.remove('link_open')
            elif child.type == 'softbreak':
                accumulator.append('\n')
            else:  # pragma: nocover
                LOGGER.error('Unsupported child type %s', child.type)
                LOGGER.debug('%r', child)
        return ''.join(output)

    async def _send_blocks(
        self,
        channel_id: str,
        blocks: list[dict[str, typing.Any]],
        plaintext: list[str],
        thread_ts: str,
    ) -> str | None:
        """Post Slack blocks, returning the message ts or ``None``."""
        if not blocks:
            return None
        try:
            response = await self.client.chat_postMessage(
                channel=channel_id,
                blocks=blocks,
                text='\n'.join(plaintext),
                thread_ts=thread_ts,
            )
        except errors.SlackApiError:
            LOGGER.exception('Error sending blocks to Slack')
            return None
        else:
            return typing.cast('str', response.data['ts'])

    async def _send_markdown(
        self,
        channel_id: str,
        markdown_text: str,
        thread_ts: str,
    ) -> str | None:
        """Post mrkdwn text, returning the message ts or ``None``."""
        try:
            response = await self.client.chat_postMessage(
                channel=channel_id,
                markdown_text=markdown_text,
                thread_ts=thread_ts,
            )
        except errors.SlackApiError:
            LOGGER.exception('Error sending markdown to Slack')
            return None
        else:
            return typing.cast('str', response.data['ts'])

    async def _send_plaintext(
        self,
        channel_id: str,
        text: str,
        thread_ts: str,
    ) -> str | None:
        """Post plain text as a fallback, returning the ts or ``None``."""
        try:
            response = await self.client.chat_postMessage(
                channel=channel_id,
                text=text,
                thread_ts=thread_ts,
            )
        except errors.SlackApiError:
            LOGGER.exception('Error sending plaintext to Slack')
            return None
        else:
            return typing.cast('str', response.data['ts'])

    @staticmethod
    def _stack_remove(
        stack: collections.deque[str], item: str
    ) -> collections.deque[str]:
        """Remove the most recent matching item from the stack."""
        stack.reverse()
        stack.remove(item)
        stack.reverse()
        return stack
