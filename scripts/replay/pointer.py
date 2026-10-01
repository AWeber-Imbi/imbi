"""JSON pointer paths and the patterns that select them.

A path is a tuple of segments. A pattern is a JSON pointer string in
which the segment ``*`` matches one segment and ``**`` matches zero or
more segments. List indexes are segments too, so ``/data/*/id`` selects
the ``id`` of each item of ``data``.
"""

import functools
import typing

Path = tuple[str, ...]


class _Missing:
    """The sentinel for a field that is not present.

    A missing field and a field that is ``null`` are different values.
    The diff keeps them apart.
    """

    _instance: typing.ClassVar[_Missing | None] = None

    def __new__(cls) -> _Missing:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return '<missing>'


MISSING = _Missing()


def escape(segment: str) -> str:
    """Escape one segment for a JSON pointer (RFC 6901)."""
    return segment.replace('~', '~0').replace('/', '~1')


def unescape(segment: str) -> str:
    """Reverse :func:`escape`."""
    return segment.replace('~1', '/').replace('~0', '~')


def to_pointer(path: Path) -> str:
    """Return the JSON pointer string of ``path``."""
    return ''.join(f'/{escape(segment)}' for segment in path)


@functools.cache
def parse(pattern: str) -> Path:
    """Split a pointer pattern into its segments.

    The empty string is the root. Every other pattern starts with
    ``/``.
    """
    if pattern == '':
        return ()
    if not pattern.startswith('/'):
        raise ValueError(f'pointer {pattern!r} must start with "/"')
    return tuple(unescape(part) for part in pattern[1:].split('/'))


def matches(pattern: str, path: Path) -> bool:
    """Return ``True`` when ``pattern`` selects ``path``."""
    return _match(parse(pattern), path)


def _match(pattern: Path, path: Path) -> bool:
    if not pattern:
        return not path
    head, rest = pattern[0], pattern[1:]
    if head == '**':
        return any(
            _match(rest, path[index:]) for index in range(len(path) + 1)
        )
    if not path:
        return False
    if head not in ('*', path[0]):
        return False
    return _match(rest, path[1:])
