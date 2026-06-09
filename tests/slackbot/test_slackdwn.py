from unittest import mock

from slack_sdk import errors

from imbi_slackbot import slackdwn
from tests import helpers


class Resp:
    def __init__(self, data) -> None:
        self.data = data


class FakeWebClient:
    def __init__(self, fail_markdown=False, fail_canvas=False) -> None:
        self.fail_markdown = fail_markdown
        self.fail_canvas = fail_canvas
        self.posts: list = []
        self.uploads: list = []
        self.canvas: dict | None = None

    async def chat_postMessage(
        self, channel, thread_ts, text=None, markdown_text=None, blocks=None
    ):
        self.posts.append(
            {
                'channel': channel,
                'thread_ts': thread_ts,
                'text': text,
                'markdown_text': markdown_text,
                'blocks': blocks,
            }
        )
        if markdown_text is not None and self.fail_markdown:
            raise errors.SlackApiError('fail', {'error': 'boom'})
        return Resp({'ts': f'ts{len(self.posts)}'})

    async def files_upload_v2(
        self, channel, content, filename, title, snippet_type, thread_ts
    ):
        self.uploads.append(
            {
                'filename': filename,
                'snippet_type': snippet_type,
                'content': content,
            }
        )
        return Resp({'files': [{'id': 'F1'}]})

    async def conversations_replies(self, channel, ts):
        return Resp({'messages': [{'ts': 'filets', 'files': [{'id': 'F1'}]}]})

    async def conversations_canvases_create(
        self, channel_id, document_content, title
    ):
        self.canvas = {'title': title, 'content': document_content}
        if self.fail_canvas:
            raise errors.SlackApiError('nocanvas', {'error': 'x'})
        return Resp({'canvas_id': 'CID'})

    async def files_info(self, file):
        return Resp({'file': {'permalink': 'http://p/CID'}})


_TABLE = '| a | b |\n| --- | --- |\n| 1 | 2 |\n'
_CODE = 'Here:\n\n```python\nprint(1)\n```\n'


class ConvertTests(helpers.TestCase):
    def test_headings_bold_links_hr(self) -> None:
        out = slackdwn.MarkdownSender._convert_to_mrkdwn(
            '## Title\n**bold** [x](http://y)\n\n---\n'
        )
        self.assertIn('*Title*', out)
        self.assertIn('*bold*', out)
        self.assertIn('<http://y|x>', out)
        self.assertIn('─', out)

    def test_code_spans_preserved(self) -> None:
        out = slackdwn.MarkdownSender._convert_to_mrkdwn('`**x**`')
        self.assertEqual('`**x**`', out)

    def test_mrkdwn_to_markdown(self) -> None:
        out = slackdwn._mrkdwn_to_markdown('<http://y|x> *b*')
        self.assertEqual('[x](http://y) **b**', out)

    def test_table_as_markdown(self) -> None:
        out = slackdwn.MarkdownSender._format_table_as_markdown(
            [['a', 'b'], ['1', '2']]
        )
        self.assertIn('| a | b |', out)
        self.assertIn('| --- | --- |', out)

    def test_table_as_text_aligns(self) -> None:
        out = slackdwn.MarkdownSender._format_table_as_text(
            [['a', 'bb'], ['111', '2']]
        )
        self.assertIn('─', out)
        self.assertEqual(3, len(out.splitlines()))


class SendTests(helpers.TestCase):
    async def test_empty_returns_nothing(self) -> None:
        client = FakeWebClient()
        sender = slackdwn.MarkdownSender(client)
        self.assertEqual([], await sender.send('C', '   ', '1.0'))

    async def test_short_markdown_path(self) -> None:
        client = FakeWebClient()
        sender = slackdwn.MarkdownSender(client)
        result = await sender.send('C', '**hi** there', '1.0')
        self.assertEqual(['ts1'], result)
        self.assertEqual('*hi* there', client.posts[0]['markdown_text'])

    async def test_markdown_failure_falls_back_to_plaintext(self) -> None:
        client = FakeWebClient(fail_markdown=True)
        sender = slackdwn.MarkdownSender(client)
        result = await sender.send('C', 'hello', '1.0')
        # First post (markdown) raised; second post used plain text.
        self.assertEqual(2, len(client.posts))
        self.assertEqual('hello', client.posts[1]['text'])
        self.assertEqual(['ts2'], result)

    async def test_table_renders_as_canvas(self) -> None:
        client = FakeWebClient()
        sender = slackdwn.MarkdownSender(client)
        result = await sender.send('C', _TABLE, '1.0')
        self.assertIsNotNone(client.canvas)
        self.assertEqual('markdown', client.canvas['content']['type'])
        # The canvas permalink is posted as a markdown message.
        self.assertIn('http://p/CID', client.posts[-1]['markdown_text'])
        self.assertTrue(result)

    async def test_table_canvas_failure_falls_back_to_snippet(self) -> None:
        client = FakeWebClient(fail_canvas=True)
        sender = slackdwn.MarkdownSender(client)
        with mock.patch.object(slackdwn.asyncio, 'sleep'):
            result = await sender.send('C', _TABLE, '1.0')
        self.assertEqual(1, len(client.uploads))
        self.assertEqual('text', client.uploads[0]['snippet_type'])
        self.assertEqual(['filets'], result)

    async def test_large_table_skips_canvas(self) -> None:
        client = FakeWebClient()
        sender = slackdwn.MarkdownSender(client)
        rows = [['x'] * 20 for _ in range(20)]  # 400 cells > 300 limit
        with mock.patch.object(slackdwn.asyncio, 'sleep'):
            result = await sender._render_table('C', rows, '1.0', None)
        self.assertIsNone(client.canvas)
        self.assertEqual(['filets'], result)

    async def test_code_block_uploaded_as_snippet(self) -> None:
        client = FakeWebClient()
        sender = slackdwn.MarkdownSender(client)
        with mock.patch.object(slackdwn.asyncio, 'sleep'):
            result = await sender._send_as_blocks('C', _CODE, '1.0')
        self.assertEqual(1, len(client.uploads))
        self.assertEqual('python', client.uploads[0]['snippet_type'])
        self.assertIn('filets', result)

    async def test_blocks_path_renders_sections_and_header(self) -> None:
        client = FakeWebClient()
        sender = slackdwn.MarkdownSender(client)
        await sender._send_as_blocks('C', '# Title\n\nA paragraph.', '1.0')
        blocks = client.posts[0]['blocks']
        kinds = [b['type'] for b in blocks]
        self.assertIn('header', kinds)
        self.assertIn('section', kinds)

    async def test_blocks_lists_quote_inline_and_divider(self) -> None:
        client = FakeWebClient()
        sender = slackdwn.MarkdownSender(client)
        text = (
            '- a\n- b\n\n'
            '1. one\n2. two\n\n'
            '> quoted\n\n'
            '[link](http://x) **b** _i_ `c`\n\n'
            '---\n'
        )
        await sender._send_as_blocks('C', text, '1.0')
        blocks = client.posts[0]['blocks']
        rendered = '\n'.join(b.get('text', {}).get('text', '') for b in blocks)
        self.assertIn('- a', rendered)
        self.assertIn('1. one', rendered)
        self.assertIn('> quoted', rendered)
        self.assertIn('<http://x|link>', rendered)
        self.assertIn('divider', [b['type'] for b in blocks])

    async def test_canvas_permalink_failure_uses_plain_link(self) -> None:
        client = FakeWebClient()
        client.files_info = mock.AsyncMock(  # type: ignore[method-assign]
            side_effect=errors.SlackApiError('no', {'error': 'x'})
        )
        sender = slackdwn.MarkdownSender(client)
        await sender.send('C', _TABLE, '1.0')
        self.assertIn('canvas CID', client.posts[-1]['markdown_text'])

    async def test_get_file_ts_no_match_returns_none(self) -> None:
        client = FakeWebClient()
        client.conversations_replies = mock.AsyncMock(  # type: ignore[method-assign]
            return_value=Resp({'messages': [{'ts': 't', 'files': []}]})
        )
        sender = slackdwn.MarkdownSender(client)
        self.assertIsNone(await sender._get_file_ts('C', '1.0', 'MISSING'))
