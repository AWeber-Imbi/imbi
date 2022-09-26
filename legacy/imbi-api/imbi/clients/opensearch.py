"""
Async OpenSearch Client Wrapper
===============================

Wraps OpenSearch client operations to use Redis as queue to perform indexing
operations asynchronously.

"""
import asyncio
import datetime
import decimal
import json
import logging
import re
import typing
import uuid

import aioredis
import opensearchpy

LOGGER = logging.getLogger(__name__)


def normalize(value_in: dict) -> dict:
    for key, value in value_in.items():
        if isinstance(value, dict):
            value_in[key] = normalize(value)
        elif isinstance(value, datetime.date):
            value_in[key] = value.isoformat()
        elif isinstance(value, datetime.datetime):
            value_in[key] = value.replace(microsecond=0).isoformat()
        elif isinstance(value, decimal.Decimal):
            value_in[key] = str(value_in[key])
        elif isinstance(value, uuid.UUID):
            value_in[key] = str(value)
        elif value == '':
            value_in[key] = None
    return value_in


def sanitize_key(value: str) -> str:
    key = value.lower().replace(' ', '_').replace('/', '_')
    return re.sub('_+', '_', key)


def sanitize_keys(value: dict) -> dict:
    for key in list(value.keys()):
        sanitized = sanitize_key(key)
        if key != sanitized:
            value[sanitized] = value[key]
            del value[key]
    for key in value.keys():
        if isinstance(value[key], dict):
            value[key] = sanitize_keys(value[key])
    return value


class OpenSearch:

    PROCESS_DELAY = 5
    PENDING_KEY = 'documents-pending'

    def __init__(self, settings: dict):
        self.client: typing.Optional[opensearchpy.AsyncOpenSearch] = None
        self.loop: typing.Optional[asyncio.AbstractEventLoop] = None
        self.redis: typing.Optional[aioredis.Redis] = None
        self.settings = settings
        self.timer_handle: typing.Optional[asyncio.TimerHandle] = None

    async def initialize(self) -> bool:
        self.loop = asyncio.get_running_loop()

        try:
            self.redis = aioredis.Redis(await aioredis.create_pool(
                self.settings.get('redis_url', 'redis://localhost:6379/2')))
        except (OSError, ConnectionRefusedError) as error:
            LOGGER.info('Error connecting to OpenSearch redis: %r', error)
            return False

        self.client = opensearchpy.AsyncOpenSearch(
            **self.settings['connection'])

        self.timer_handle = self.loop.call_soon(
            lambda: asyncio.ensure_future(self._process()))
        return True

    async def create_index(self, index: str) -> bool:
        LOGGER.debug('Creating %s index in OpenSearch', index)
        try:
            await self.client.indices.create(index)
        except opensearchpy.exceptions.RequestError as err:
            if 'resource_already_exists_exception' not in err.error:
                LOGGER.warning('Index creation error: %r', err)
                return False
        return True

    async def create_mapping(self, index: str, mappings: dict) -> bool:
        try:
            await self.client.indices.put_mapping(
                index=index, body={'properties': mappings})
        except opensearchpy.exceptions.RequestError as err:
            LOGGER.debug('Mapping update failure: %r', err)
            return False
        return True

    async def delete_document(self, index: str, document_id: str) -> None:
        LOGGER.debug('Deleting %s from %s', document_id, index)
        try:
            await self.client.delete(index, document_id)
        except (
            opensearchpy.exceptions.NotFoundError,
            opensearchpy.exceptions.RequestError
        ) as err:
            LOGGER.warning('Deletion of %s:%s failed: %r',
                           index, document_id, err)

    async def documents_pending(self) -> int:
        """Return the number of documents pending indexing"""
        return await self.redis.scard(self.PENDING_KEY)

    async def index_document(self,
                             index: str,
                             document_id: str,
                             document: dict,
                             sync: bool = False) -> None:
        """Queue a document to be added the OpenSearch index"""
        LOGGER.debug('Queueing %s:%s to be indexed', index, document_id)
        if not sync:
            await self.redis.set(
                f'{index}:{document_id}',
                json.dumps(normalize(sanitize_keys(document)), indent=0))
            await self.redis.sadd(self.PENDING_KEY, f'{index}:{document_id}')
            return
        await self._index_document(
            index, document_id, normalize(sanitize_keys(document)))

    async def search(self, index: str, query: str, max_results: int = 1000) \
            -> typing.Dict[str, typing.List[dict]]:
        result = await self.client.search(
            body={
                'query': {
                    'query_string': {'query': query, 'size': max_results}}},
            index=index)
        return {'hits': [r['_source'] for r in result['hits']['hits']]}

    async def stop(self) -> None:
        if self.timer_handle and not self.timer_handle.cancelled():
            self.timer_handle.cancel()
        if self.client is not None:
            await self.client.close()

    async def _process(self) -> None:
        if await self._process_document():
            self.timer_handle = self.loop.call_soon(
                lambda: asyncio.ensure_future(self._process()))
            return
        self.timer_handle = self.loop.call_later(
            self.PROCESS_DELAY, lambda: asyncio.ensure_future(self._process()))

    async def _process_document(self) -> bool:
        """Index a single document in the index, if any are queued"""
        key = await self.redis.spop(self.PENDING_KEY)
        if not key:
            return False

        index, document_id = key.decode('utf-8').split(':')
        LOGGER.debug('Processing %s:%s', index, document_id)
        document = await self.redis.get(key)
        if not document:
            LOGGER.warning('Failed to load %s from redis', key)
            return False

        if not await self._index_document(
                index, document_id, json.loads(document)):
            return False

        result = await asyncio.gather(
            self.redis.delete(key),
            self.redis.scard(self.PENDING_KEY))
        LOGGER.debug(
            'Processing of %s:%s is complete with %i documents pending',
            index, document_id, result[1])
        return True

    async def _index_document(self,
                              index: str,
                              document_id: str,
                              document: dict) -> bool:
        """Invoked to index a document in ElasticSearch"""
        try:
            await self.client.index(
                index, body=document, id=document_id)
        except opensearchpy.RequestError as err:
            LOGGER.warning('Failed to index %s in %s: %s',
                           document_id, index, err)
            return False
        return True
