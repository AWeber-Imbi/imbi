"""Read and write a recording directory.

A recording is a directory with ``meta.json`` and
``exchanges.jsonl`` (one exchange on each line). Recordings contain
production data: keep them out of the repository.
"""

import json
import typing

from scripts.replay import models

if typing.TYPE_CHECKING:
    import pathlib

EXCHANGES = 'exchanges.jsonl'
META = 'meta.json'


def write(
    directory: pathlib.Path,
    exchanges: list[models.Exchange],
    meta: dict[str, typing.Any],
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / EXCHANGES).open('w') as handle:
        for exchange in exchanges:
            handle.write(exchange.model_dump_json() + '\n')
    (directory / META).write_text(json.dumps(meta, indent=2, sort_keys=True))


def read(directory: pathlib.Path) -> list[models.Exchange]:
    with (directory / EXCHANGES).open() as handle:
        return [
            models.Exchange.model_validate_json(line)
            for line in handle
            if line.strip()
        ]


def read_meta(directory: pathlib.Path) -> dict[str, typing.Any]:
    path = directory / META
    if not path.exists():
        return {}
    return typing.cast('dict[str, typing.Any]', json.loads(path.read_text()))
