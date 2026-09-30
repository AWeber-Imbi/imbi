"""The audit's copy of the schema rules must match ``schemata/``.

The tests import ``tables`` only when they run, so ``--write`` works when
the module is out of date.

Run this file with ``--write`` to regenerate
``imbi/common/db/etl/audit/tables.py`` after a schema change::

    uv run python libraries/common/tests/test_etl_audit_schema.py --write

"""

import pathlib
import sys
import typing
import unittest

import yaml

from imbi.common.db.etl.audit import schema

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SCHEMATA = REPO_ROOT / 'schemata'
TABLES_MODULE = (
    REPO_ROOT
    / 'libraries'
    / 'common'
    / 'src'
    / 'imbi'
    / 'common'
    / 'db'
    / 'etl'
    / 'audit'
    / 'tables.py'
)

HEADER = '''\
"""The schema rules of ``schemata/``. Generated; do not edit.

Regenerate with
``python libraries/common/tests/test_etl_audit_schema.py --write``.
"""

# ruff: noqa: E501

from imbi.common.db.etl.audit.schema import (
    Check,
    Column,
    Domain,
    ForeignKey,
    Table,
    Unique,
)

'''


def _load(path: pathlib.Path) -> dict[str, typing.Any]:
    return typing.cast(dict[str, typing.Any], yaml.safe_load(path.read_text()))


def _checks(document: dict[str, typing.Any]) -> tuple[schema.Check, ...]:
    return tuple(
        schema.Check(check['name'], check['expression'])
        for check in document.get('check_constraints') or ()
    )


def derive_domains() -> dict[str, schema.Domain]:
    domains: dict[str, schema.Domain] = {}
    for path in sorted((SCHEMATA / 'domains' / 'public').glob('*.yaml')):
        document = _load(path)
        name = f'public.{document["name"]}'
        domains[name] = schema.Domain(
            name, document['data_type'], _checks(document)
        )
    return domains


def _table(document: dict[str, typing.Any]) -> schema.Table:
    name = document['name']
    columns = tuple(
        schema.Column(
            column['name'],
            column['data_type'],
            column.get('nullable', True),
            'default' in column,
        )
        for column in document['columns']
    )
    uniques = [schema.Unique(f'{name}_pkey', tuple(document['primary_key']))]
    for key in document.get('unique_constraints') or ():
        # A list of columns, or a map with columns and nulls_not_distinct.
        key_columns = key['columns'] if isinstance(key, dict) else key
        uniques.append(
            schema.Unique(
                f'{name}_{"_".join(key_columns)}_key',
                tuple(key_columns),
                None,
                isinstance(key, dict) and bool(key.get('nulls_not_distinct')),
            )
        )
    for index in document.get('indexes') or ():
        if not index.get('unique'):
            continue
        uniques.append(
            schema.Unique(
                index['name'],
                tuple(
                    part.get('name') or part['expression']
                    for part in index['columns']
                ),
                index.get('where'),
                bool(index.get('nulls_not_distinct')),
            )
        )
    foreign_keys = tuple(
        schema.ForeignKey(
            key['name'],
            tuple(key['columns']),
            key['references']['name'].removeprefix('public.'),
            tuple(key['references']['columns']),
        )
        for key in document.get('foreign_keys') or ()
    )
    return schema.Table(
        name, columns, _checks(document), tuple(uniques), foreign_keys
    )


def derive_tables() -> dict[str, schema.Table]:
    return {
        table.name: table
        for table in (
            _table(_load(path))
            for path in sorted((SCHEMATA / 'tables' / 'public').glob('*.yaml'))
        )
    }


def _call(value: tuple[typing.Any, ...]) -> str:
    """Render a NamedTuple as a call with positional arguments."""
    return f'{type(value).__name__}{tuple(value)!r}'


def _group(name: str, values: tuple[tuple[typing.Any, ...], ...]) -> list[str]:
    if not values:
        return []
    return [
        f'        {name}=(',
        *(f'            {_call(value)},' for value in values),
        '        ),',
    ]


def render() -> str:
    lines = [HEADER, '# fmt: off', 'DOMAINS: dict[str, Domain] = {']
    for name, domain in derive_domains().items():
        lines.append(f'    {name!r}: Domain(')
        lines.append(f'        {domain.name!r}, {domain.data_type!r},')
        lines.extend(_group('checks', domain.checks))
        lines.append('    ),')
    lines.append('}')
    lines.append('')
    lines.append('TABLES: dict[str, Table] = {')
    for name, table in derive_tables().items():
        lines.append(f'    {name!r}: Table(')
        lines.append(f'        {table.name!r},')
        lines.extend(_group('columns', table.columns))
        lines.extend(_group('checks', table.checks))
        lines.extend(_group('uniques', table.uniques))
        lines.extend(_group('foreign_keys', table.foreign_keys))
        lines.append('    ),')
    lines.append('}')
    lines.append('# fmt: on')
    return '\n'.join(lines) + '\n'


def write() -> None:
    TABLES_MODULE.write_text(render())


class AuditSchemaTestCase(unittest.TestCase):
    """``tables.py`` holds the rules of every table and domain."""

    def test_tables_match_schemata(self) -> None:
        from imbi.common.db.etl.audit import tables

        self.assertEqual(
            tables.TABLES,
            derive_tables(),
            'Regenerate audit/tables.py: see the docstring of this test.',
        )

    def test_domains_match_schemata(self) -> None:
        from imbi.common.db.etl.audit import tables

        self.assertEqual(tables.DOMAINS, derive_domains())

    def test_table_count(self) -> None:
        self.assertEqual(len(derive_tables()), 74)


if __name__ == '__main__':
    if sys.argv[1:] == ['--write']:
        write()
    else:
        unittest.main()
