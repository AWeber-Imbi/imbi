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
    from imbi_common import lifespan  # requires [server] extra
except ImportError:
    lifespan = None  # type: ignore[assignment]

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
if lifespan is not None:
    __all__.append('lifespan')
