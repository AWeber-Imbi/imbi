"""FastAPI dependency injection for StorageClient."""

import typing

import fastapi
from imbi_common.lifespan import InjectLifespan

from imbi_api import lifespans

from .client import StorageClient


def _get_storage_client(
    context: InjectLifespan,
) -> StorageClient:
    return context.get_state(lifespans.storage_hook)


InjectStorageClient = typing.Annotated[
    StorageClient, fastapi.Depends(_get_storage_client)
]
