"""Shared Cypher property-template helpers for AGE queries."""

import re
import typing

# Property names must look like identifiers because the same string is
# inlined into a psycopg ``.format()`` template as the parameter
# placeholder (``{key}``). Anything outside this set could either break
# placeholder substitution or smuggle Cypher fragments past the
# backtick escape.
_IDENT_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


def _check_identifier(name: str) -> None:
    if not _IDENT_RE.match(name):
        raise ValueError(f'Invalid Cypher property name: {name!r}')


def escape_prop(name: str) -> str:
    """Escape a Cypher property name with backticks."""
    return '`' + name.replace('`', '``') + '`'


def props_template(props: dict[str, typing.Any]) -> str:
    """Build a Cypher property-map template with double-escaped braces.

    Raises:
        ValueError: if any key is not a bare identifier.
    """
    if not props:
        return ''
    for k in props:
        _check_identifier(k)
    pairs = [f'{escape_prop(k)}: {{{k}}}' for k in props]
    return '{{' + ', '.join(pairs) + '}}'


def set_clause(alias: str, props: dict[str, typing.Any]) -> str:
    """Build a Cypher SET clause from a property dict.

    Raises:
        ValueError: if any key is not a bare identifier.
    """
    if not props:
        return ''
    for k in props:
        _check_identifier(k)
    assignments = ', '.join(
        f'{alias}.{escape_prop(k)} = {{{k}}}' for k in props
    )
    return f'SET {assignments}'
