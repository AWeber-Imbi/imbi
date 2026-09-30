"""Mask the fields that are different on each run.

Normalization changes only the fields that a rule names. It does not
sort lists, it does not remove fields, and a ``null`` stays ``null``:
a rule replaces a value that is present and not ``null`` with
:data:`MASK`.
"""

import fnmatch
import typing

from scripts.replay import models, pointer

MASK = '<normalized>'


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
        return MASK
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
