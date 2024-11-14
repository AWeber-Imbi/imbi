from __future__ import annotations

import asyncio
import copy
import dataclasses
import logging
import typing

from imbi import models, opensearch

if typing.TYPE_CHECKING:
    from imbi import app

LOGGER = logging.getLogger(__name__)

# Make sure that the field names match models.OperationsLog.SQL
OPS_LOG = {
    'id': {
        'type': 'integer'
    },
    'occurred_at': {
        'type': 'date'
    },
    'recorded_at': {
        'type': 'date'
    },
    'recorded_by': {
        'type': 'text'
    },
    'display_name': {
        'type': 'text',
    },
    'completed_at': {
        'type': 'date'
    },
    'project_id': {
        'type': 'integer'
    },
    'project_name': {
        'type': 'text'
    },
    'environment': {
        'type': 'text'
    },
    'change_type': {
        'type': 'text'
    },
    'description': {
        'type': 'text'
    },
    'link': {
        'type': 'text'
    },
    'notes': {
        'type': 'text'
    },
    'performed_by': {
        'type': 'text'
    },
    'ticket_slug': {
        'type': 'text'
    },
    'version': {
        'type': 'text'
    }
}


class OperationsLogIndex(opensearch.SearchIndex[models.OperationsLog]):
    """Class for interacting with the OpenSearch OperationsLog index"""

    INDEX = 'operations-log'

    def __init__(self, application) -> None:
        super().__init__(application, models.operations_log)

    async def _build_mappings(self):
        return copy.deepcopy(OPS_LOG)

    def _serialize_document(
            self, doc: models.OperationsLog) -> dict[str, typing.Any]:
        return dataclasses.asdict(doc)


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
