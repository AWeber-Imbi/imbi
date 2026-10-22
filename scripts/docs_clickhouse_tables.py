"""Print the table list of docs/common/api/clickhouse.md.

One row per section of the ClickHouse `schemata.toml`, with the engine
and order key read from its DDL, and the Iggy topics that feed it from
`TOPICS` in `imbi.common.iggy`. `TOPICS` is read with `ast`, because
importing `imbi.common.iggy` loads the native Iggy SDK. Paste the
output between the BEGIN and END GENERATED comments of the page.

    uv run python scripts/docs_clickhouse_tables.py
"""

import ast
import pathlib
import re
import sys
import tomllib

COMMON = (
    pathlib.Path(__file__).resolve().parent.parent
    / 'libraries/common/src/imbi/common'
)


def topics() -> dict[str, tuple[str, ...]]:
    tree = ast.parse((COMMON / 'iggy/__init__.py').read_text())
    for node in tree.body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == 'TOPICS'
            and node.value is not None
        ):
            return ast.literal_eval(node.value)
    raise RuntimeError('TOPICS not found')


def describe(query: str) -> tuple[str, str, str]:
    kind = 'view'
    if 'MATERIALIZED VIEW' in query:
        kind = 'materialized view'
    elif 'CREATE TABLE' in query:
        kind = 'table'
    engine = re.search(r'ENGINE = \{replicated\}(\w+)', query)
    order = re.search(r'^ORDER BY (.+?);?$', query, re.MULTILINE)
    return (
        kind,
        f'`{engine.group(1)}`' if engine else '',
        f'`{order.group(1)}`' if order else '',
    )


def main() -> None:
    schemata = tomllib.loads((COMMON / 'clickhouse/schemata.toml').read_text())
    streams = topics()
    lines = [
        '| Name | Kind | Engine | Order key | Iggy topics |',
        '|---|---|---|---|---|',
    ]
    for name, section in schemata.items():
        kind, engine, order = describe(section['query'])
        feeds = ', '.join(f'`{t}`' for t in streams.get(name, ()))
        lines.append(f'| `{name}` | {kind} | {engine} | {order} | {feeds} |')
    sys.stdout.write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
