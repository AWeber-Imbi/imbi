"""Check that every generated table in docs/ matches its script.

A generated block starts with ``<!-- BEGIN GENERATED: <script> [args] -->``
and ends with ``<!-- END GENERATED -->``. This script runs each named
script with its arguments and compares the output with the block body.

    uv run python scripts/docs_check_generated.py          # check
    uv run python scripts/docs_check_generated.py --fix    # rewrite

Exit status 1 means at least one block is stale.
"""

import functools
import pathlib
import re
import shlex
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BLOCK = re.compile(
    r'(<!-- BEGIN GENERATED: (?P<cmd>[^\n]*?) -->\n)'
    r'(?P<body>.*?)'
    r'(<!-- END GENERATED -->)',
    re.DOTALL,
)


@functools.cache
def render(cmd: str) -> str:
    """Run one generator command and return the block body to embed."""
    args = shlex.split(cmd)
    # The command comes from a marker in this repo's own docs, not from
    # user input.
    out = subprocess.run(  # noqa: S603
        [sys.executable, str(ROOT / args[0]), *args[1:]],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return '\n' + out.strip() + '\n\n'


def check(path: pathlib.Path, fix: bool) -> list[str]:
    """Return the stale blocks of one page, rewriting them if *fix*."""
    text = path.read_text()
    stale = [
        f'{path.relative_to(ROOT)}: {match["cmd"]}'
        for match in BLOCK.finditer(text)
        if match['body'].strip() != render(match['cmd']).strip()
    ]
    if fix and stale:
        path.write_text(
            BLOCK.sub(lambda m: m[1] + render(m['cmd']) + m[4], text)
        )
    return stale


def main(fix: bool) -> int:
    stale = []
    for path in sorted((ROOT / 'docs').rglob('*.md')):
        if 'site' not in path.relative_to(ROOT / 'docs').parts:
            stale.extend(check(path, fix))
    label = 'fixed' if fix else 'stale'
    sys.stdout.writelines(f'{label}: {item}\n' for item in stale)
    return 1 if stale and not fix else 0


if __name__ == '__main__':
    sys.exit(main('--fix' in sys.argv[1:]))
