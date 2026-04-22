"""Shared Cypher property-template helpers for AGE queries."""

import typing


def escape_prop(name: str) -> str:
    """Escape a Cypher property name with backticks."""
    return '`' + name.replace('`', '``') + '`'


def props_template(props: dict[str, typing.Any]) -> str:
    """Build a Cypher property-map template with double-escaped braces."""
    if not props:
        return ''
    pairs = [f'{escape_prop(k)}: {{{k}}}' for k in props]
    return '{{' + ', '.join(pairs) + '}}'


def set_clause(alias: str, props: dict[str, typing.Any]) -> str:
    """Build a Cypher SET clause from a property dict."""
    if not props:
        return ''
    assignments = ', '.join(
        f'{alias}.{escape_prop(k)} = {{{k}}}' for k in props
    )
    return f'SET {assignments}'
