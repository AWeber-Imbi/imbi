"""Tests for the chunk module."""

import unittest

from imbi.common.graph import chunk


class TextChunkTests(unittest.TestCase):
    def test_basic_chunking(self) -> None:
        value = 'a' * 1000
        chunks = list(chunk.text(value, chunk_size=500, overlap=50))
        self.assertEqual(3, len(chunks))
        self.assertEqual(500, len(chunks[0]))
        self.assertEqual(500, len(chunks[1]))

    def test_overlap_content(self) -> None:
        value = 'abcdefghij' * 10  # 100 chars
        chunks = list(chunk.text(value, chunk_size=30, overlap=10))
        # Second chunk starts at position 20
        self.assertEqual(chunks[0][20:30], chunks[1][:10])

    def test_small_input_single_chunk(self) -> None:
        value = 'hello'
        chunks = list(chunk.text(value, chunk_size=500))
        self.assertEqual(1, len(chunks))
        self.assertEqual('hello', chunks[0])

    def test_empty_input(self) -> None:
        chunks = list(chunk.text(''))
        self.assertEqual(0, len(chunks))

    def test_overlap_validation(self) -> None:
        with self.assertRaises(ValueError):
            list(chunk.text('test', chunk_size=10, overlap=10))

    def test_overlap_greater_than_chunk(self) -> None:
        with self.assertRaises(ValueError):
            list(chunk.text('test', chunk_size=10, overlap=20))

    def test_zero_chunk_size(self) -> None:
        with self.assertRaises(ValueError):
            list(chunk.text('test', chunk_size=0))

    def test_negative_overlap(self) -> None:
        with self.assertRaises(ValueError):
            list(chunk.text('test', overlap=-1))


class MarkdownChunkTests(unittest.TestCase):
    def test_splits_on_headings(self) -> None:
        md = '# Title\nIntro\n# Second\nBody'
        chunks = list(chunk.markdown(md))
        self.assertEqual(2, len(chunks))

    def test_empty_chunks_skipped(self) -> None:
        md = ''
        chunks = list(chunk.markdown(md))
        self.assertEqual(0, len(chunks))

    def test_single_section(self) -> None:
        md = '# Only Section\nSome text.'
        chunks = list(chunk.markdown(md))
        self.assertEqual(1, len(chunks))


class ContentRoutingTests(unittest.TestCase):
    def test_markdown_mimetype(self) -> None:
        md = '# Title\nText'
        chunks = list(chunk.content('text/markdown', md))
        self.assertGreaterEqual(len(chunks), 1)

    def test_x_markdown_mimetype(self) -> None:
        md = '# Title\nText'
        chunks = list(
            chunk.content('text/x-markdown', md),
        )
        self.assertGreaterEqual(len(chunks), 1)

    def test_plaintext_fallback(self) -> None:
        value = 'a' * 1000
        chunks = list(
            chunk.content(
                'text/plain',
                value,
                chunk_size=500,
                overlap=50,
            ),
        )
        self.assertGreater(len(chunks), 1)
