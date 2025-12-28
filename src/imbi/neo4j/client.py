import asyncio
import contextlib
import logging
import typing

import cypherantic
import neo4j
import pydantic
from neo4j import exceptions

from imbi import settings, version

from . import constants

LOGGER = logging.getLogger(__name__)

ModelType = typing.TypeVar('ModelType', bound=pydantic.BaseModel)
SourceNode = typing.TypeVar('SourceNode', bound=pydantic.BaseModel)
TargetNode = typing.TypeVar('TargetNode', bound=pydantic.BaseModel)
RelationshipProperties = typing.TypeVar(
    'RelationshipProperties', bound=pydantic.BaseModel
)
EdgeType = typing.TypeVar('EdgeType')


class Neo4j:
    instance = None

    def __init__(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._settings = settings.Neo4j()
        self._neo4j = self._create_client()

    @classmethod
    def get_instance(cls) -> typing.Self:
        if cls.instance is None:
            cls.instance = Neo4j()
        else:
            current_loop = asyncio.get_event_loop()
            if cls.instance._loop != current_loop:
                LOGGER.debug('Event loop changed, reinitializing Neo4j')
                cls.instance._loop = current_loop
                cls.instance._neo4j = cls.instance._create_client()
        return cls.instance

    async def aclose(self) -> None:
        LOGGER.debug('Closing Neo4j')
        await self._neo4j.close()

    async def initialize(self) -> None:
        LOGGER.debug('Initializing Neo4j')
        async with self.session() as session:
            for index in constants.INDEXES:
                try:
                    await session.run(index)
                except exceptions.ConstraintError as err:
                    LOGGER.debug('Error creating index: %s', err)
                    continue

    @contextlib.asynccontextmanager
    async def session(
        self,
        default_access_mode: str = neo4j.WRITE_ACCESS,
        fetch_size: int = 1000,
    ) -> typing.AsyncGenerator[cypherantic.SessionType, None]:
        async with self._neo4j.session(
            database=self._settings.database,
            default_access_mode=default_access_mode,
            fetch_size=fetch_size,
        ) as session:
            yield session  # type: ignore

    def _create_client(self) -> neo4j.AsyncDriver:
        return neo4j.AsyncGraphDatabase.driver(
            uri=str(self._settings.url),
            auth=(self._settings.user, self._settings.password),
            keep_alive=self._settings.keep_alive,
            liveness_check_timeout=self._settings.liveness_check_timeout,
            max_connection_lifetime=self._settings.max_connection_lifetime,
            user_agent=f'imbi/{version}',
        )
