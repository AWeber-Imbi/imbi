import asyncio
import dataclasses
import logging
import typing

from imbi import models
if typing.TYPE_CHECKING:
    from imbi import app

LOGGER = logging.getLogger(__name__)

OPS_LOG = {
    'id': {'type': 'integer'},
    'recorded_at': {'type': 'date'},
    'recorded_by': {'type': 'text'},
    'completed_at': {'type': 'date'},
    'project_id': {'type': 'integer'},
    'project_name': {'type': 'text'},
    'environment': {'type': 'text'},
    'change_type': {'type': 'text'},
    'description': {'type': 'text'},
    'link': {'type': 'text'},
    'notes': {'type': 'text'},
    'ticket_slug': {'type': 'text'},
    'version': {'type': 'text'}
}


class OperationsLogIndex:
    """Class for interacting with the OpenSearch OperationsLog index"""

    INDEX = 'operations-log'

    def __init__(self, application: 'app.Application'):
        self.application = application

    async def create_index(self):
        LOGGER.debug('Creating operations-log index in OpenSearch')
        await self.application.opensearch.create_index(self.INDEX)

    async def create_mapping(self):
        await self.application.opensearch.create_mapping(
            self.INDEX, await self._build_mappings())

    async def delete_document(self, ops_log_id: typing.Union[int, str]):
        await self.application.opensearch.delete_document(
            self.INDEX, str(ops_log_id))

    async def index_document(self, ops_log: models.OperationsLog):
        await self.application.opensearch.index_document(
            self.INDEX, str(ops_log.id), self._ops_log_to_dict(ops_log), True)

    async def search(self, query: str, max_results: int = 1000) \
            -> typing.Dict[str, typing.List[dict]]:
        return await self.application.opensearch.search(
            self.INDEX, query, max_results)

    async def _build_mappings(self):
        defn = dict(OPS_LOG)
        return defn

    @staticmethod
    def _ops_log_to_dict(value: models.OperationsLog) -> dict:
        return dataclasses.asdict(value)


class RequestHandlerMixin:

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.search_index = OperationsLogIndex(self.application)

    async def index_document(self, ops_log_id: typing.Union[int, str]) -> None:
        value = await models.operations_log(ops_log_id, self.application)
        await self.search_index.index_document(value)


async def initialize(application: 'app.Application', build=False):
    index = OperationsLogIndex(application)
    LOGGER.info('Creating the operations-log index')
    await index.create_index()
    LOGGER.info('Creating the operations-log index mappings')
    await index.create_mapping()

    if build:
        async with application.postgres_connector() as conn:
            result = await conn.execute(
                'SELECT id FROM v1.operations_log ORDER BY id', {},
                'build-operations-log-index')
            ids = [row['id'] for row in result]
            LOGGER.info('Queueing %i operations-logs for indexing', len(ids))
            for ops_log_id in ids:
                value = await models.operations_log(ops_log_id, application)
                await index.index_document(value)
            LOGGER.info('Queued %i opeations-logs for indexing', len(ids))
            while True:
                pending = \
                    await index.application.opensearch.documents_pending()
                if not pending:
                    break
                LOGGER.info('Waiting for %i projects to index', pending)
                await asyncio.sleep(2)
            LOGGER.info('Indexing complete')
