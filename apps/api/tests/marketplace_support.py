"""Fixtures for the marketplace and agent platform tests (ADR 0022)."""

import pathlib

from imbi.api.harness import marketplaces

#: ``.claude-plugin/marketplace.json`` of github.com/anthropics/claude-code
#: at b0b7bed9820350bb0942e32c7f00752a99ea3555.
FIXTURE = (
    pathlib.Path(__file__).parent
    / 'fixtures'
    / 'marketplaces'
    / 'claude-code.json'
)


def reader(files: dict[str, str]) -> marketplaces.FileReader:
    """Return a reader of ``files``, by repository path. A path that
    ``files`` does not have is missing."""

    async def read(path: str) -> str | None:
        return files.get(path)

    return read
