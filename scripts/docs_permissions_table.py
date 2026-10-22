"""Print the permission table of docs/admin/roles-and-permissions.md.

The table comes from the seed (`imbi.api.auth.seed`): one row per
permission in `STANDARD_PERMISSIONS`, one column per role in
`DEFAULT_ROLES`. Paste the output between the BEGIN and END GENERATED
comments of the page.

    uv run python scripts/docs_permissions_table.py
"""

import sys

from imbi.api.auth import seed


def main() -> None:
    roles = [(role[0], set(role[4])) for role in seed.DEFAULT_ROLES]
    slugs = ' | '.join(f'`{slug}`' for slug, _ in roles)
    lines = [
        f'| Permission | Description | {slugs} |',
        '|---|---|' + ':-:|' * len(roles),
    ]
    for name, _, _, description in seed.STANDARD_PERMISSIONS:
        marks = ' | '.join(
            'yes' if name in grants else '' for _, grants in roles
        )
        lines.append(f'| `{name}` | {description} | {marks} |')
    sys.stdout.write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
