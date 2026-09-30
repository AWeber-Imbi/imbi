"""The NOT NULL columns and unique keys that ``schemata/`` declares.

The reconciliation checks that the target catalog has each of them. A
constraint that the catalog has is enforced by PostgreSQL, so the report
labels it ``schema-enforced`` and does not count rows.
"""

import dataclasses
import pathlib
import typing

import yaml  # type: ignore[import-untyped]

from imbi.common.db.etl import mapping

ENFORCED = 'schema-enforced'
MISSING = 'missing from the target'


@dataclasses.dataclass(frozen=True, slots=True)
class UniqueKey:
    #: The index name, or a description for a key with no name in YAML.
    label: str
    #: Column names or index expressions, in order.
    keys: tuple[str, ...]
    partial: bool


@dataclasses.dataclass(frozen=True, slots=True)
class Declared:
    not_null: tuple[str, ...]
    unique_keys: tuple[UniqueKey, ...]


def load(directory: pathlib.Path, table: str) -> Declared:
    """Read ``<directory>/<table>.yaml``."""
    path = directory / f'{table}.yaml'
    if not path.is_file():
        raise mapping.EtlError(f'No schema file for {table}: {path}')
    document = typing.cast(
        dict[str, typing.Any], yaml.safe_load(path.read_text())
    )
    columns = typing.cast(
        list[dict[str, typing.Any]], document.get('columns') or []
    )
    primary = tuple(
        str(c)
        for c in typing.cast(list[str], document.get('primary_key') or [])
    )
    not_null = [
        str(c['name']) for c in columns if c.get('nullable', True) is False
    ]
    not_null.extend(c for c in primary if c not in not_null)
    keys: list[UniqueKey] = []
    if primary:
        keys.append(
            UniqueKey(f'primary key ({", ".join(primary)})', primary, False)
        )
    for constraint in typing.cast(
        list[list[str] | dict[str, typing.Any]],
        document.get('unique_constraints') or [],
    ):
        # A list of columns, or a map with columns and an optional name.
        if isinstance(constraint, dict):
            names = tuple(str(c) for c in constraint['columns'])
            label = str(constraint.get('name') or '') or None
        else:
            names = tuple(str(c) for c in constraint)
            label = None
        keys.append(
            UniqueKey(label or f'unique ({", ".join(names)})', names, False)
        )
    for index in typing.cast(
        list[dict[str, typing.Any]], document.get('indexes') or []
    ):
        if not index.get('unique'):
            continue
        parts = typing.cast(list[dict[str, str]], index.get('columns') or [])
        keys.append(
            UniqueKey(
                str(index['name']),
                tuple(
                    str(p.get('name') or p.get('expression')) for p in parts
                ),
                bool(index.get('where')),
            )
        )
    return Declared(tuple(not_null), tuple(keys))


def normalize(key: str) -> str:
    """Compare an index key without its outer parentheses and spaces."""
    text = key.replace(' ', '')
    while text.startswith('(') and text.endswith(')'):
        text = text[1:-1]
    return text
