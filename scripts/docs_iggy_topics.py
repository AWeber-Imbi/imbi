"""Print the stream table of docs/architecture/events.md.

One row per stream in `imbi.common.iggy.TOPICS`, with its topics and
the engine and TTL of the ClickHouse table of the same name in
`imbi/common/clickhouse/schemata.toml`. Both files are parsed, not
imported, so the script does not load the native Iggy client. Paste
the output between the BEGIN and END GENERATED comments of the page.

    uv run python scripts/docs_iggy_topics.py
"""

import ast
import pathlib
import re
import sys
import tomllib

COMMON = pathlib.Path(__file__).parents[1] / 'libraries/common/src/imbi/common'


def topics() -> dict[str, tuple[str, ...]]:
    tree = ast.parse((COMMON / 'iggy/__init__.py').read_text())
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and node.target.id == 'TOPICS':
            return ast.literal_eval(node.value)
    raise RuntimeError('TOPICS not found')


def main() -> None:
    schemata = tomllib.loads((COMMON / 'clickhouse/schemata.toml').read_text())
    lines = [
        '| Stream and ClickHouse table | Topics | Engine | TTL |',
        '|---|---|---|---|',
    ]
    for stream, names in topics().items():
        query = schemata.get(stream, {}).get('query', '')
        engine = re.search(r'ENGINE = \{replicated\}(\w+\([^)]*\))', query)
        ttl = re.search(r'^TTL (.+?);?$', query, re.MULTILINE)
        lines.append(
            f'| `{stream}` | {", ".join(f"`{t}`" for t in names)} '
            f'| {f"`{engine.group(1)}`" if engine else "not found"} '
            f'| {f"`{ttl.group(1)}`" if ttl else "none"} |'
        )
    sys.stdout.write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
