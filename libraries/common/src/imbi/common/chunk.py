"""Text chunking for embedding generation.

Provides overlapping text chunking and markdown-aware
splitting for use with the embeddings module.
"""

import collections.abc

import markdown_it


def text(
    value: str,
    chunk_size: int = 500,
    overlap: int = 50,
) -> collections.abc.Iterator[str]:
    """Create overlapping chunks from a text blob.

    Yields successive slices of *value* where each slice is
    at most *chunk_size* characters and consecutive slices
    overlap by *overlap* characters.

    Raises :class:`ValueError` if *chunk_size* is not
    positive, *overlap* is negative, or *overlap* is not
    smaller than *chunk_size*.

    """
    if chunk_size <= 0:
        raise ValueError('chunk_size must be > 0.')
    if overlap < 0:
        raise ValueError('overlap must be >= 0.')
    if overlap >= chunk_size:
        raise ValueError('overlap must be < chunk_size.')
    for i in range(0, len(value), chunk_size - overlap):
        yield value[i : i + chunk_size]


def markdown(value: str) -> collections.abc.Iterator[str]:
    """Chunk markdown by headings, respecting structure.

    Splits the input on heading boundaries so each chunk
    corresponds roughly to a section.

    """
    md = markdown_it.MarkdownIt()
    tokens = md.parse(value)
    current_chunk: list[str] = []
    for token in tokens:
        if token.type == 'heading_open' and current_chunk:
            yield ''.join(current_chunk)
            current_chunk = []
        current_chunk.append(token.markup + token.content)
    if current_chunk:
        joined = ''.join(current_chunk)
        if joined.strip():
            yield joined


def content(
    mimetype: str,
    value: str,
    chunk_size: int = 500,
    overlap: int = 50,
) -> collections.abc.Iterator[str]:
    """Route to the appropriate chunker by MIME type."""
    normalized = mimetype.split(';')[0].strip().lower()
    if normalized in (
        'text/markdown',
        'text/x-markdown',
    ):
        yield from markdown(value)
    else:
        yield from text(value, chunk_size, overlap)
