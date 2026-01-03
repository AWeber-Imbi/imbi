"""Imbi common library - shared functionality for Imbi ecosystem."""

from importlib import metadata

from imbi_common import (
    auth,
    blueprints,
    clickhouse,
    logging,
    models,
    neo4j,
    settings,
)

try:
    version = metadata.version('imbi-common')
except metadata.PackageNotFoundError:
    version = '0.0.0'

__all__ = [
    'auth',
    'blueprints',
    'clickhouse',
    'logging',
    'models',
    'neo4j',
    'settings',
    'version',
]
