"""Print a permission table for one admin page.

Each argument is a permission name or a prefix that ends in ``:``, for
example ``webhook:`` or ``admin:maintenance:``. The table has one row
per matching permission in `STANDARD_PERMISSIONS`, with the roles of
`DEFAULT_ROLES` that grant it. Paste the output between the BEGIN and
END GENERATED comments of the page.

    uv run python scripts/docs_permissions_subset.py webhook:
"""

import sys

from imbi.api.auth import seed


def main(patterns: list[str]) -> None:
    lines = ['| Permission | Lets you | Roles that have it |', '|---|---|---|']
    for name, _, _, description in seed.STANDARD_PERMISSIONS:
        if not any(
            name.startswith(p) if p.endswith(':') else name == p
            for p in patterns
        ):
            continue
        roles = ', '.join(
            f'`{role[0]}`' for role in seed.DEFAULT_ROLES if name in role[4]
        )
        lines.append(f'| `{name}` | {description} | {roles or "none"} |')
    sys.stdout.write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main(sys.argv[1:])
