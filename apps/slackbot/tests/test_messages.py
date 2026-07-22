import base64
from unittest import mock

from apps.slackbot.tests import helpers
from imbi.slackbot import messages


class FakeSlack:
    def __init__(self, names=None, raise_users=False) -> None:
        self._names = names or {}
        self._raise = raise_users

    async def users_info(self, user):
        if self._raise:
            raise RuntimeError('nope')
        name = self._names.get(user, user)
        return {'user': {'profile': {'display_name': name}}}


class FakeResp:
    def __init__(self, status=200, headers=None, content=b'') -> None:
        self.status_code = status
        self.headers = headers or {}
        self.content = content

    async def aiter_bytes(self):
        # Yield in chunks so the size guard is exercised mid-stream.
        chunk = 64 * 1024
        for offset in range(0, len(self.content), chunk) or [0]:
            yield self.content[offset : offset + chunk]


class _Stream:
    def __init__(self, resp) -> None:
        self._resp = resp

    async def __aenter__(self):
        if isinstance(self._resp, Exception):
            raise self._resp
        return self._resp

    async def __aexit__(self, *_exc):
        return False


class FakeHTTP:
    def __init__(self, resp) -> None:
        self._resp = resp
        self.closed = False

    def stream(self, method, url, follow_redirects=False):
        return _Stream(self._resp)

    async def aclose(self):
        self.closed = True


def _patch_http(resp):
    return mock.patch.object(messages.httpx, 'AsyncClient', lambda **_k: resp)


class FileToBlockTests(helpers.TestCase):
    def test_pdf(self) -> None:
        block = messages._file_to_block('application/pdf', b'%PDF-1.4')
        self.assertEqual('document', block['type'])
        self.assertEqual('application/pdf', block['source']['media_type'])

    def test_image(self) -> None:
        block = messages._file_to_block('image/png;charset=binary', b'\x89PNG')
        self.assertEqual('image', block['type'])
        self.assertEqual('image/png', block['source']['media_type'])
        self.assertEqual(
            base64.b64encode(b'\x89PNG').decode(), block['source']['data']
        )

    def test_text_like(self) -> None:
        block = messages._file_to_block('application/json', b'{"a": 1}')
        self.assertEqual('text', block['type'])
        self.assertEqual('{"a": 1}', block['text'])

    def test_octet_stream_decodable(self) -> None:
        block = messages._file_to_block('application/octet-stream', b'hello')
        self.assertEqual('hello', block['text'])

    def test_octet_stream_binary(self) -> None:
        block = messages._file_to_block(
            'application/octet-stream', b'\xff\xfe\x00'
        )
        self.assertIn('could not be decoded', block['text'])

    def test_unsupported(self) -> None:
        block = messages._file_to_block('application/zip', b'PK')
        self.assertIn('unsupported file type', block['text'])


class FileBlocksTests(helpers.TestCase):
    async def test_downloads_and_converts(self) -> None:
        resp = FakeResp(headers={'content-type': 'text/plain'}, content=b'hi')
        blocks = await messages._file_blocks(
            FakeHTTP(resp), [{'url_private': 'http://x/f'}]
        )
        self.assertEqual([{'type': 'text', 'text': 'hi'}], blocks)

    async def test_skips_no_url(self) -> None:
        blocks = await messages._file_blocks(FakeHTTP(FakeResp()), [{}])
        self.assertEqual([], blocks)

    async def test_non_200_skipped(self) -> None:
        resp = FakeResp(status=404)
        blocks = await messages._file_blocks(
            FakeHTTP(resp), [{'url_private': 'http://x/f'}]
        )
        self.assertEqual([], blocks)

    async def test_download_error_skipped(self) -> None:
        blocks = await messages._file_blocks(
            FakeHTTP(messages.httpx.ConnectError('boom')),
            [{'url_private': 'http://x/f'}],
        )
        self.assertEqual([], blocks)

    async def test_too_large(self) -> None:
        big = b'x' * (messages.MAX_FILE_BYTES + 1)
        resp = FakeResp(headers={'content-type': 'text/plain'}, content=big)
        blocks = await messages._file_blocks(
            FakeHTTP(resp), [{'url_private': 'http://x/f'}]
        )
        self.assertIn('exceeds the maximum size', blocks[0]['text'])


class ReconstructTests(helpers.TestCase):
    async def _run(self, replies, names=None, bot='BOT', cap=30):
        with _patch_http(FakeHTTP(FakeResp())):
            return await messages.reconstruct(
                FakeSlack(names=names), 'xoxb', replies, bot, cap
            )

    async def test_attribution_and_ts(self) -> None:
        replies = [{'user': 'U1', 'text': 'hi', 'ts': '1.0'}]
        msgs = await self._run(replies, names={'U1': 'Ada'})
        self.assertEqual(1, len(msgs))
        self.assertEqual('user', msgs[0]['role'])
        self.assertEqual('<@Ada> [ts=1.0] hi', msgs[0]['content'])

    async def test_mention_conversion(self) -> None:
        replies = [{'user': 'U1', 'text': '<@U2> ping', 'ts': '1.0'}]
        msgs = await self._run(replies, names={'U1': 'Ada', 'U2': 'Bob'})
        self.assertIn('@Bob ping', msgs[0]['content'])

    async def test_distinct_users_coalesced_with_attribution(self) -> None:
        replies = [
            {'user': 'U1', 'text': 'one', 'ts': '1'},
            {'user': 'U2', 'text': 'two', 'ts': '2'},
        ]
        msgs = await self._run(replies, names={'U1': 'Ada', 'U2': 'Bob'})
        # Both are user-role and must coalesce to keep alternation, but
        # each speaker stays attributed in the merged text.
        self.assertEqual(1, len(msgs))
        self.assertIn('<@Ada> [ts=1] one', msgs[0]['content'])
        self.assertIn('<@Bob> [ts=2] two', msgs[0]['content'])

    async def test_assistant_role_and_leading_drop(self) -> None:
        replies = [
            {'user': 'BOT', 'text': 'earlier', 'ts': '1'},
            {'user': 'U1', 'text': 'hi', 'ts': '2'},
            {'user': 'BOT', 'text': 'reply', 'ts': '3'},
        ]
        msgs = await self._run(replies, names={'U1': 'Ada'})
        self.assertEqual(2, len(msgs))
        self.assertEqual('user', msgs[0]['role'])
        self.assertEqual('assistant', msgs[1]['role'])
        self.assertEqual('reply', msgs[1]['content'])

    async def test_skips_subtype_no_user_and_empty(self) -> None:
        replies = [
            {'subtype': 'channel_join', 'user': 'U1', 'text': 'joined'},
            {'text': 'no user'},
            {'user': 'U1', 'text': '   ', 'ts': '1'},
            {'user': 'U1', 'text': 'real', 'ts': '2'},
        ]
        msgs = await self._run(replies, names={'U1': 'Ada'})
        self.assertEqual(1, len(msgs))
        self.assertIn('real', msgs[0]['content'])

    async def test_cap(self) -> None:
        replies = [
            {'user': 'U1', 'text': f'm{i}', 'ts': str(i)} for i in range(10)
        ]
        msgs = await self._run(replies, names={'U1': 'Ada'}, cap=3)
        self.assertEqual(1, len(msgs))
        self.assertIn('m9', msgs[0]['content'])
        self.assertNotIn('m0', msgs[0]['content'])

    async def test_files_produce_block_content(self) -> None:
        replies = [
            {
                'user': 'U1',
                'text': 'see this',
                'ts': '1',
                'files': [{'url_private': 'http://x/f'}],
            }
        ]
        resp = FakeResp(
            headers={'content-type': 'image/png'}, content=b'\x89PNG'
        )
        with _patch_http(FakeHTTP(resp)):
            msgs = await messages.reconstruct(
                FakeSlack(names={'U1': 'Ada'}), 'xoxb', replies, 'BOT', 30
            )
        content = msgs[0]['content']
        self.assertIsInstance(content, list)
        self.assertEqual('text', content[0]['type'])
        self.assertEqual('image', content[1]['type'])

    async def test_file_only_message_kept(self) -> None:
        replies = [
            {
                'user': 'U1',
                'ts': '1',
                'files': [{'url_private': 'http://x/f'}],
            }
        ]
        # An image attachment forces block content (non-text block).
        resp = FakeResp(
            headers={'content-type': 'image/png'}, content=b'\x89PNG'
        )
        with _patch_http(FakeHTTP(resp)):
            msgs = await messages.reconstruct(
                FakeSlack(names={'U1': 'Ada'}), 'xoxb', replies, 'BOT', 30
            )
        self.assertEqual(1, len(msgs))
        self.assertIsInstance(msgs[0]['content'], list)
        # Leading attribution block, then the image block.
        self.assertEqual('<@Ada> [ts=1]', msgs[0]['content'][0]['text'])
        self.assertEqual('image', msgs[0]['content'][1]['type'])

    async def test_display_name_lookup_failure_falls_back_to_id(self) -> None:
        replies = [{'user': 'U1', 'text': 'hi', 'ts': '1'}]
        with _patch_http(FakeHTTP(FakeResp())):
            msgs = await messages.reconstruct(
                FakeSlack(raise_users=True), 'xoxb', replies, 'BOT', 30
            )
        self.assertIn('<@U1> [ts=1] hi', msgs[0]['content'])
