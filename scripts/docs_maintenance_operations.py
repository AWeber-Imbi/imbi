"""Print the operation table of docs/admin/maintenance.md.

The table comes from the maintenance registry
(`apps/api/src/imbi/api/maintenance/registry.py`), which is also what
the Maintenance page shows. The script parses the file and does not
import it, because the import needs the native Iggy client. Paste the
output between the BEGIN and END GENERATED comments of the page.

    uv run python scripts/docs_maintenance_operations.py
"""

import ast
import pathlib
import sys

REGISTRY = (
    pathlib.Path(__file__).parent.parent
    / 'apps/api/src/imbi/api/maintenance/registry.py'
)


def main() -> None:
    lines = ['| Operation | Slug | What it does |', '|---|---|---|']
    for node in ast.walk(ast.parse(REGISTRY.read_text())):
        if not (
            isinstance(node, ast.Call)
            and getattr(node.func, 'id', None) == 'OperationDefinition'
        ):
            continue
        fields = {
            kw.arg: kw.value.value
            for kw in node.keywords
            if isinstance(kw.value, ast.Constant)
        }
        description = fields['description'].replace('|', '\\|')
        lines.append(
            f'| **{fields["label"]}** | `{fields["slug"]}` | {description} |'
        )
    sys.stdout.write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
