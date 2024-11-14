from __future__ import annotations

import asyncio
import dataclasses
import logging
import typing

import imbi.opensearch
from imbi import errors, models
from imbi.clients import opensearch

if typing.TYPE_CHECKING:
    from imbi import app

LOGGER = logging.getLogger(__name__)

FACT_DATA_TYPES = {
    'boolean': 'boolean',
    'date': 'date',
    'decimal': 'float',
    'integer': 'integer',
    'string': 'text',
    'timestamp': 'date'
}

PROJECT = {
    'archived': {
        'type': 'boolean'
    },
    'components': {
        'type': 'nested',
        'properties': {
            'name': {
                'type': 'text',
                'fields': {
                    'keyword': {
                        'type': 'keyword',
                        'ignore_above': 256
                    }
                }
            },
            'version': {
                'type': 'text',
                'fields': {
                    'keyword': {
                        'type': 'keyword',
                        'ignore_above': 16
                    }
                }
            },
        }
    },
    'created_at': {
        'type': 'date'
    },
    'created_by': {
        'type': 'text'
    },
    'dependencies': {
        'type': 'integer'
    },
    'description': {
        'type': 'text'
    },
    'environments': {
        'type': 'text'
    },
    'gitlab_project_id': {
        'type': 'text'
    },
    'id': {
        'type': 'integer'
    },
    'last_modified_at': {
        'type': 'date'
    },
    'last_modified_by': {
        'type': 'text'
    },
    'name': {
        'type': 'text'
    },
    'namespace': {
        'type': 'text'
    },
    'namespace_slug': {
        'type': 'text'
    },
    'pagerduty_service_id': {
        'type': 'text'
    },
    'project_score': {
        'type': 'integer'
    },
    'project_type': {
        'type': 'text'
    },
    'project_type_slug': {
        'type': 'text'
    },
    'sentry_project_slug': {
        'type': 'text'
    },
    'slug': {
        'type': 'text'
    },
    'sonarqube_project_key': {
        'type': 'text'
    },
}


class ProjectIndex(imbi.opensearch.SearchIndex[models.Project]):
    """Class for interacting with the OpenSearch Project index"""

    INDEX = 'projects'

    def __init__(self, application) -> None:
        super().__init__(application, models.project)

    async def searchable_fields(self) -> list[dict]:
        fields = []
        index_mappings = await self._build_mappings()
        for key, defn in index_mappings.items():
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

        async with self.application.postgres_connector(
                on_error=self._on_postgres_error) as cursor:
            result = await cursor.execute(
                'SELECT name, data_type FROM v1.project_fact_types;')
            for row in result:
                fields.append({
                    'name': row['name'].lower().replace(' ', '_'),
                    'type': FACT_DATA_TYPES[row['data_type']],
                    'count': 0,
                    'scripted': False,
                    'searchable': True,
                    'aggregatable': True,
                    'readFromDocValues': True
                })
        return fields

    async def _build_mappings(self) -> dict:
        defn = dict(PROJECT)
        async with self.application.postgres_connector(
                on_error=self._on_postgres_error) as cursor:
            result = await cursor.execute(
                'SELECT name, data_type FROM v1.project_fact_types;')
            for row in result:
                defn[f'facts.{opensearch.sanitize_key(row["name"])}'] = {
                    'type': FACT_DATA_TYPES[row['data_type']]
                }
            result = await cursor.execute(
                'SELECT link_type FROM v1.project_link_types;')
            for row in result:
                defn[f'links.{opensearch.sanitize_key(row["link_type"])}'] = {
                    'type': 'text'
                }
            result = await cursor.execute('SELECT name FROM v1.environments;')
            for row in result:
                defn[f'urls.{opensearch.sanitize_key(row["name"])}'] = {
                    'type': 'text'
                }
            result = await cursor.execute('SELECT name FROM v1.integrations;')
            for row in result:
                defn[f'identifiers.{opensearch.sanitize_key(row["name"])}'] = {
                    'type': 'text'
                }
        return defn

    def _serialize_document(self, doc: models.Project) -> dict:
        output = dataclasses.asdict(doc)
        for key in ['namespace', 'project_type']:
            output[f'{key}_slug'] = output[key]['slug']
            output[key] = output[key]['name']
        return output

    @staticmethod
    def _on_postgres_error(metric_name: str, exc: Exception) -> None:
        LOGGER.error('Failed to execute query for collection %s: %s',
                     metric_name, exc)
        raise errors.DatabaseError(f'Error executing {metric_name}', error=exc)


class RequestHandlerMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.search_index = ProjectIndex(self.application)

    async def index_document(self, project_id: typing.Union[int, str]) -> None:
        value = await models.project(project_id, self.application)
        await self.search_index.index_document(value)


async def initialize(application: 'app.Application', build=False):
    index = ProjectIndex(application)
    LOGGER.info('Creating the project index')
    await index.create_index()
    LOGGER.info('Creating the project index mappings')
    await index.create_mapping()

    if build:
        async with application.postgres_connector() as conn:
            result = await conn.execute(
                'SELECT id FROM v1.projects ORDER BY id', {},
                'build-project-index')
            ids = [row['id'] for row in result]
            LOGGER.info('Queueing %i projects for indexing', len(ids))
            for project_id in ids:
                value = await models.project(project_id, application)
                await index.index_document(value)
            LOGGER.info('Queued %i projects for indexing', len(ids))
            while True:
                pending = \
                    await index.application.opensearch.documents_pending()
                if not pending:
                    break
                LOGGER.info('Waiting for %i projects to index', pending)
                await asyncio.sleep(2)
            LOGGER.info('Indexing complete')
