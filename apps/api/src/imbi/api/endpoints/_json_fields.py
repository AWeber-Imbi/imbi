"""Helpers for round-tripping JSON-typed node properties.

Apache AGE stores nested list/dict properties as JSON strings, so
endpoints serialize those fields on the way in and parse them back on
the way out. The same field-list-driven serialize/deserialize pair was
duplicated across ``integrations`` and ``projects``; this module
is the single home for it.

``fields`` maps each JSON field name to the default value used when the
stored value is missing, ``None``, or malformed.
"""

from __future__ import annotations

import json
import typing

JSONFields = dict[str, list[typing.Any] | dict[str, typing.Any]]


def serialize_json_fields(
    props: dict[str, typing.Any],
    fields: JSONFields,
) -> dict[str, typing.Any]:
    """Serialize list/dict fields to JSON strings for graph storage."""
    result = dict(props)
    for key in fields:
        if key in result and not isinstance(result[key], str):
            result[key] = json.dumps(result[key])
    return result


def deserialize_json_fields(
    record: dict[str, typing.Any],
    fields: JSONFields,
) -> dict[str, typing.Any]:
    """Deserialize JSON string fields back to Python objects.

    A missing, ``None``, or malformed value falls back to the field's
    default rather than raising.
    """
    obj = dict(record)
    for key, default in fields.items():
        val = obj.get(key)
        if isinstance(val, str):
            try:
                obj[key] = json.loads(val)
            except json.JSONDecodeError, TypeError:
                obj[key] = default
        elif val is None:
            obj[key] = default
    return obj


__all__ = ['deserialize_json_fields', 'serialize_json_fields']
