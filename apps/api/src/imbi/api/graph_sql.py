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


def props_template(props: dict[str, typing.Any]) -> typing.LiteralString:
    """Build a Cypher property-map template with double-escaped braces.

    The return type is ``LiteralString`` because the builder accepts
    only validated identifier keys (see ``_check_identifier``) and a
    fixed template body, so the result is safe to feed into
    ``db.execute(query: LiteralString, ...)``.

    Raises:
        ValueError: if any key is not a bare identifier.
    """
    if not props:
        return ''
    for k in props:
        _check_identifier(k)
    pairs = [f'{escape_prop(k)}: {{{k}}}' for k in props]
    return typing.cast(  # type: ignore[redundant-cast]
        typing.LiteralString, '{{' + ', '.join(pairs) + '}}'
    )


def set_clause(
    alias: str, props: dict[str, typing.Any]
) -> typing.LiteralString:
    """Build a Cypher SET clause from a property dict.

    Returns a ``LiteralString`` for the same reason as
    :func:`props_template` — the builder only accepts validated
    identifier keys.

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
    return typing.cast(  # type: ignore[redundant-cast]
        typing.LiteralString, f'SET {assignments}'
    )
