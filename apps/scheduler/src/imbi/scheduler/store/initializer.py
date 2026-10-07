"""Create the scheduler's Postgres schema from ``schemata.toml``.

The DDL itself lives in :mod:`imbi.common.relational`, which other plain
Postgres schemas share.
"""

import logging
import pathlib
import typing

from imbi.common import relational
from imbi.scheduler import settings

LOGGER = logging.getLogger(__name__)

SCHEMATA_PATH = pathlib.Path(__file__).parent / 'schemata.toml'


def load_schemata() -> dict[str, typing.Any]:
    """Return the parsed schema definition."""
    return relational.load_schemata(SCHEMATA_PATH)


async def initialize() -> None:
    """Create the scheduler schema, tables, and indexes.

    The advisory lock is keyed on the schema name so two deployments using
    different schemas in one database do not queue behind each other.
    """
    schema = settings.Scheduler().schema_name
    await relational.initialize(
        schema, load_schemata(), f'imbi.scheduler.initialize.{schema}'
    )
    LOGGER.info('Scheduler schema %r initialized', schema)
