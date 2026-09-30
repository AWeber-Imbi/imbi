"""Mask the fields that are different on each run.

Normalization changes only the fields that a rule names. It does not
sort lists, it does not remove fields, and a ``null`` stays ``null``:
a rule replaces a value that is present and not ``null`` with
``<normalized:TYPE>``, so a change of the JSON type is still a
difference.
"""

import fnmatch
import typing

from scripts.replay import models, pointer

MASK = '<normalized:{}>'


def mask(value: typing.Any) -> str:
    """Return the mask of ``value``, which keeps its JSON type."""
    if isinstance(value, bool):
        kind = 'bool'
    elif isinstance(value, int):
        kind = 'int'
    elif isinstance(value, float):
        kind = 'float'
    elif isinstance(value, str):
        kind = 'str'
    elif isinstance(value, dict):
        kind = 'object'
    elif isinstance(value, list):
        kind = 'array'
    else:
        kind = type(value).__name__
    return MASK.format(kind)


def pointers_for(
    rules: list[models.NormalizeRule], exchange: models.Exchange
) -> list[str]:
    """Return the pointer patterns that apply to ``exchange``."""
    selected = [
        rule.pointer
        for rule in rules
        if fnmatch.fnmatchcase(exchange.route, rule.route)
        or fnmatch.fnmatchcase(exchange.key, rule.route)
    ]
    return selected + list(exchange.normalize)


def apply(value: typing.Any, patterns: list[str]) -> typing.Any:
    """Return a copy of ``value`` with the selected fields masked."""
    if not patterns:
        return value
    return _walk(value, (), patterns)


def _walk(
    value: typing.Any, path: pointer.Path, patterns: list[str]
) -> typing.Any:
    if value is not None and any(
        pointer.matches(pattern, path) for pattern in patterns
    ):
        return mask(value)
    if isinstance(value, dict):
        items = typing.cast('dict[str, typing.Any]', value)
        return {
            key: _walk(item, (*path, key), patterns)
            for key, item in items.items()
        }
    if isinstance(value, list):
        entries = typing.cast('list[typing.Any]', value)
        return [
            _walk(item, (*path, str(index)), patterns)
            for index, item in enumerate(entries)
        ]
    return value
