import asyncio
import datetime
import decimal
import json
import logging
import typing
import uuid

import aiopg
import aioredis
import opensearchpy
from psycopg2 import extras

from imbi import mappings

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


def sanitize_keys(value: dict) -> dict:
    for key in list(value.keys()):
        sanitized = key.lower().replace(' ', '_')
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

    def __init__(self, settings: dict, postgres_url: str):
        self.client: typing.Optional[opensearchpy.AsyncOpenSearch] = None
        self.loop: typing.Optional[asyncio.AbstractEventLoop] = None
        self.postgres_url = postgres_url
        self.redis: typing.Optional[aioredis.Redis] = None
        self.settings = settings
        self.timer_handle: typing.Optional[asyncio.TimerHandle] = None

    async def initialize(self) -> bool:
        self.loop = asyncio.get_running_loop()

        try:
            self.redis = aioredis.Redis(
                await aioredis.create_pool(self.settings['redis_url']))
        except (OSError, ConnectionRefusedError) as error:
            LOGGER.info('Error connecting to Stats redis: %r', error)
            return False

        self.client = opensearchpy.AsyncOpenSearch(
            **self.settings['connection'])

        LOGGER.debug('Creating projects index in OpenSearch')
        try:
            await self.client.indices.create('projects')
        except opensearchpy.exceptions.RequestError as err:
            if err.error != 'resource_already_exists_exception':
                LOGGER.debug('Index creation error: %r', err)

        try:
            await self.client.indices.put_mapping(
                index='projects',
                body={'properties': await self._build_mappings()})
        except opensearchpy.exceptions.RequestError as err:
            LOGGER.debug('Mapping update failure: %r', err)

        self.timer_handle = self.loop.call_soon(
            lambda: asyncio.ensure_future(self._process()))
        return True

    async def delete_document(self, index: str, document_id: str) -> None:
        LOGGER.debug('Deleting %s from %s', document_id, index)
        try:
            await self.client.delete(index, document_id)
        except opensearchpy.exceptions.RequestError as err:
            LOGGER.warning('Deletion of %s:%s failed: %r',
                           index, document_id, err)

    async def index_document(self,
                             index: str,
                             document_id: str,
                             document: dict) -> None:
        """Queue a document to be added the OpenSearch index"""
        LOGGER.debug('Queueing %s:%s to be indexed', index, document_id)
        await self.redis.set(
            f'{index}:{document_id}',
            json.dumps(normalize(sanitize_keys(document)), indent=0))
        await self.redis.sadd(self.PENDING_KEY, f'{index}:{document_id}')

    async def search_fields(self) -> typing.List[typing.Dict]:
        fields = []
        for key, defn in mappings.PROJECT.items():
            try:
                fields.append({
                    'name': key,
                    'type': defn['type'],
                    'count': 0,
                    'scripted': False,
                    'searchable': True,
                    'aggregatable': True,
                    'readFromDocValues': True
                })
            except KeyError:
                pass

        async with aiopg.create_pool(self.postgres_url) as pool:
            async with pool.acquire() as conn:
                async with conn.cursor(
                        cursor_factory=extras.RealDictCursor) as cursor:
                    await cursor.execute(
                        'SELECT name, data_type FROM v1.project_fact_types;')
                    async for row in cursor:
                        fields.append({
                            'name': row['name'].lower().replace(' ', '_'),
                            'type': mappings.FACT_DATA_TYPES[row['data_type']],
                            'count': 0,
                            'scripted': False,
                            'searchable': True,
                            'aggregatable': True,
                            'readFromDocValues': True
                        })
        return fields

    async def stop(self) -> None:
        if self.timer_handle and not self.timer_handle.cancelled():
            self.timer_handle.cancel()
        if self.client is not None:
            await self.client.close()

    async def _build_mappings(self) -> dict:
        definition = dict(mappings.PROJECT)
        facts = {}
        links = {}
        urls = {}
        async with aiopg.create_pool(self.postgres_url) as pool:
            async with pool.acquire() as conn:
                async with conn.cursor(
                        cursor_factory=extras.RealDictCursor) as cursor:
                    await cursor.execute(
                        'SELECT name, data_type FROM v1.project_fact_types;')
                    async for row in cursor:
                        facts[row['name'].lower().replace(' ', '_')] = {
                            'type': mappings.FACT_DATA_TYPES[row['data_type']]
                        }
                    await cursor.execute(
                        'SELECT link_type FROM v1.project_link_types;')
                    async for row in cursor:
                        links[row['link_type'].lower().replace(' ', '_')] = {
                            'type': 'text'
                        }
                    await cursor.execute(
                        'SELECT name FROM v1.environments;')
                    async for row in cursor:
                        urls[row['name'].lower().replace(' ', '_')] = {
                            'type': 'text'
                        }
        return definition

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

        try:
            await self.client.index(
                index, body=json.loads(document), id=document_id)
        except opensearchpy.RequestError as err:
            LOGGER.warning('Failed to index %s in %s: %s',
                           document_id, index, err)
            return False

        result = await asyncio.gather(
            self.redis.delete(key),
            self.redis.scard(self.PENDING_KEY))
        LOGGER.debug(
            'Processing of %s:%s is complete with %i documents pending',
            index, document_id, result[1])
        return True
